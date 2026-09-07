import unittest

from workspace_deletion import (
    WorkspaceDeletionError,
    discover_workspace_deletions,
    execute_workspace_deletions,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._payload


class RequestSequence:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        return self.responses.pop(0)


class WorkspaceDeletionTests(unittest.TestCase):
    def test_discovery_supports_mpe_pagination(self):
        continuation = (
            "https://api.fabric.microsoft.com/v1/workspaces/ws-1/"
            "managedPrivateEndpoints?continuationToken=next"
        )
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {
                "value": [{"id": "mpe-1", "name": "Key Vault"}],
                "continuationUri": continuation,
            }),
            FakeResponse(200, {
                "value": [{
                    "id": "mpe-2",
                    "name": "Cognitive Services",
                    "connectionState": {"status": "Approved"},
                }]
            }),
        ])

        preview = discover_workspace_deletions(["ws-1"], {}, get, lambda _seconds: None)

        self.assertEqual("Workspace One", preview[0].name)
        self.assertEqual(["mpe-1", "mpe-2"], [mpe.id for mpe in preview[0].managed_private_endpoints])
        self.assertEqual("Approved", preview[0].managed_private_endpoints[1].status)

    def test_discovery_rejects_continuation_for_another_workspace(self):
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {
                "value": [],
                "continuationUri": (
                    "https://api.fabric.microsoft.com/v1/workspaces/ws-2/"
                    "managedPrivateEndpoints?continuationToken=next"
                ),
            }),
        ])

        with self.assertRaisesRegex(WorkspaceDeletionError, "invalid continuation URI"):
            discover_workspace_deletions(["ws-1"], {}, get, lambda _seconds: None)

    def test_discovery_failure_occurs_before_any_delete(self):
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {"value": []}),
            FakeResponse(403, {"error": {"message": "Forbidden"}}),
        ])
        delete_calls = []

        with self.assertRaisesRegex(WorkspaceDeletionError, "Could not inspect workspace ws-2"):
            execute_workspace_deletions(
                ["ws-1", "ws-2"],
                {},
                get,
                lambda *args, **kwargs: delete_calls.append(args),
                lambda _seconds: None,
            )

        self.assertEqual([], delete_calls)

    def test_deletes_and_verifies_mpe_before_workspace(self):
        events = []
        get_responses = iter([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {"value": [{"id": "mpe-1", "name": "Key Vault"}]}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(404),
            FakeResponse(200, {"value": []}),
        ])

        def get(url, headers, timeout):
            events.append(("GET", url))
            return next(get_responses)

        def delete(url, headers, timeout):
            events.append(("DELETE", url))
            return FakeResponse(200)

        completed = execute_workspace_deletions(
            ["ws-1"], {}, get, delete, lambda _seconds: None
        )

        self.assertEqual(("ws-1",), completed)
        endpoint_delete = events.index((
            "DELETE",
            "https://api.fabric.microsoft.com/v1/workspaces/ws-1/managedPrivateEndpoints/mpe-1",
        ))
        workspace_delete = events.index((
            "DELETE", "https://api.fabric.microsoft.com/v1/workspaces/ws-1"
        ))
        self.assertLess(endpoint_delete, workspace_delete)

    def test_existing_mpe_blocks_workspace_and_remaining_batch(self):
        delete_calls = []
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {"value": [{"id": "mpe-1", "name": "Key Vault"}]}),
            FakeResponse(200, {"displayName": "Workspace Two"}),
            FakeResponse(200, {"value": []}),
            FakeResponse(200, {"id": "mpe-1"}),
        ])

        with self.assertRaisesRegex(WorkspaceDeletionError, "still exists"):
            execute_workspace_deletions(
                ["ws-1", "ws-2"],
                {},
                get,
                lambda url, headers, timeout: (
                    delete_calls.append(url) or FakeResponse(200)
                ),
                lambda _seconds: None,
                verification_attempts=1,
            )

        self.assertEqual(1, len(delete_calls))
        self.assertIn("managedPrivateEndpoints/mpe-1", delete_calls[0])

    def test_waits_with_bounded_backoff_for_eventual_endpoint_removal(self):
        sleeps = []
        delete = RequestSequence([FakeResponse(200), FakeResponse(204)])
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {"value": [{"id": "mpe-1", "name": "Key Vault"}]}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(200, {"id": "mpe-1"}),
            FakeResponse(404),
            FakeResponse(200, {"value": []}),
        ])

        completed = execute_workspace_deletions(
            ["ws-1"], {}, get, delete, sleeps.append
        )

        self.assertEqual(("ws-1",), completed)
        self.assertEqual([1, 2, 4, 8, 10, 10], sleeps)
        self.assertEqual(
            "https://api.fabric.microsoft.com/v1/workspaces/ws-1",
            delete.calls[-1],
        )

    def test_retries_throttled_delete_and_treats_404_as_absent(self):
        sleeps = []
        delete = RequestSequence([
            FakeResponse(429, headers={"Retry-After": "2"}),
            FakeResponse(404),
            FakeResponse(204),
        ])
        get = RequestSequence([
            FakeResponse(200, {"displayName": "Workspace One"}),
            FakeResponse(200, {"value": [{"id": "mpe-1", "name": "Key Vault"}]}),
            FakeResponse(404),
            FakeResponse(200, {"value": []}),
        ])

        completed = execute_workspace_deletions(
            ["ws-1"], {}, get, delete, sleeps.append
        )

        self.assertEqual(("ws-1",), completed)
        self.assertEqual([2.0], sleeps)
        self.assertEqual(3, len(delete.calls))


if __name__ == "__main__":
    unittest.main()