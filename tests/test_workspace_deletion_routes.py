import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("FABRIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")

import app as application
from workspace_deletion import (
    ManagedPrivateEndpoint,
    WorkspaceDeletionError,
    WorkspaceDeletionPreview,
)


class WorkspaceDeletionRouteTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    @patch.object(application.requests, "delete")
    @patch.object(application, "get_headers", return_value={"Authorization": "Bearer hidden"})
    @patch.object(application, "discover_workspace_deletions")
    def test_preview_discovers_without_deleting(
        self, discover, _get_headers, request_delete
    ):
        discover.return_value = (
            WorkspaceDeletionPreview(
                id="ws-1",
                name="Workspace One",
                managed_private_endpoints=(
                    ManagedPrivateEndpoint("mpe-1", "Key Vault", "Approved"),
                ),
            ),
        )
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_review_token"] = "review-token"

        response = self.client.post(
            "/modify-workspaces/delete",
            data={"review_token": "review-token", "workspace_ids": '["ws-1"]'},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Workspace One", response.data)
        self.assertIn(b"Key Vault", response.data)
        self.assertIn(b'id="deletion-progress"', response.data)
        self.assertIn(b"Waiting for Fabric verification", response.data)
        self.assertNotIn(b"checkbox.disabled = true", response.data)
        request_delete.assert_not_called()
        with self.client.session_transaction() as flask_session:
            confirmation = flask_session["workspace_delete_confirmation"]
        self.assertEqual(["ws-1"], confirmation["workspace_ids"])

    @patch.object(application, "discover_workspace_deletions")
    def test_invalid_review_token_never_discovers_workspaces(self, discover):
        response = self.client.post(
            "/modify-workspaces/delete",
            data={"review_token": "invalid", "workspace_ids": '["ws-1"]'},
        )

        self.assertEqual(302, response.status_code)
        discover.assert_not_called()

    @patch.object(application, "get_headers", return_value={"Authorization": "Bearer hidden"})
    @patch.object(application, "execute_workspace_deletions", return_value=("ws-1",))
    def test_confirmation_uses_session_workspace_ids(self, execute, _get_headers):
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_confirmation"] = {
                "token": "valid-token",
                "workspace_ids": ["ws-1"],
                "created_at": int(time.time()),
            }

        response = self.client.post(
            "/modify-workspaces/delete/confirm",
            data={
                "confirmation_token": "valid-token",
                "confirmed": "yes",
                "workspace_ids": '["attacker-controlled"]',
            },
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual(["ws-1"], execute.call_args.args[0])
        with self.client.session_transaction() as flask_session:
            self.assertEqual(["ws-1"], flask_session["deleted_workspace_ids"])
            self.assertNotIn("workspace_delete_confirmation", flask_session)

    @patch.object(application, "execute_workspace_deletions")
    def test_missing_confirmation_never_executes_deletion(self, execute):
        response = self.client.post(
            "/modify-workspaces/delete/confirm",
            data={"confirmation_token": "missing", "confirmed": "yes"},
        )

        self.assertEqual(302, response.status_code)
        execute.assert_not_called()

    @patch.object(application, "execute_workspace_deletions")
    def test_mismatched_confirmation_never_executes_deletion(self, execute):
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_confirmation"] = {
                "token": "valid-token",
                "workspace_ids": ["ws-1"],
                "created_at": int(time.time()),
            }

        response = self.client.post(
            "/modify-workspaces/delete/confirm",
            data={"confirmation_token": "wrong-token", "confirmed": "yes"},
        )

        self.assertEqual(302, response.status_code)
        execute.assert_not_called()

    @patch.object(application, "execute_workspace_deletions")
    def test_expired_confirmation_never_executes_deletion(self, execute):
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_confirmation"] = {
                "token": "expired-token",
                "workspace_ids": ["ws-1"],
                "created_at": int(time.time()) - application.DELETE_CONFIRMATION_TTL_SECONDS - 1,
            }

        response = self.client.post(
            "/modify-workspaces/delete/confirm",
            data={"confirmation_token": "expired-token", "confirmed": "yes"},
        )

        self.assertEqual(302, response.status_code)
        execute.assert_not_called()

    @patch.object(application, "get_headers", return_value={"Authorization": "Bearer hidden"})
    @patch.object(application, "execute_workspace_deletions", return_value=("ws-1",))
    def test_confirmation_token_cannot_be_replayed(self, execute, _get_headers):
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_confirmation"] = {
                "token": "single-use-token",
                "workspace_ids": ["ws-1"],
                "created_at": int(time.time()),
            }
        form = {"confirmation_token": "single-use-token", "confirmed": "yes"}

        first_response = self.client.post("/modify-workspaces/delete/confirm", data=form)
        second_response = self.client.post("/modify-workspaces/delete/confirm", data=form)

        self.assertEqual(302, first_response.status_code)
        self.assertEqual(302, second_response.status_code)
        execute.assert_called_once()

    @patch.object(application, "get_headers", return_value={"Authorization": "Bearer hidden"})
    @patch.object(application, "execute_workspace_deletions")
    def test_failure_records_only_completed_workspaces(self, execute, _get_headers):
        execute.side_effect = WorkspaceDeletionError(
            "Managed private endpoint still exists.", ("ws-1",)
        )
        with self.client.session_transaction() as flask_session:
            flask_session["workspace_delete_confirmation"] = {
                "token": "valid-token",
                "workspace_ids": ["ws-1", "ws-2"],
                "created_at": int(time.time()),
            }

        response = self.client.post(
            "/modify-workspaces/delete/confirm",
            data={"confirmation_token": "valid-token", "confirmed": "yes"},
        )

        self.assertEqual(302, response.status_code)
        with self.client.session_transaction() as flask_session:
            self.assertEqual(["ws-1"], flask_session["deleted_workspace_ids"])
            messages = flask_session.get("_flashes", [])
        self.assertTrue(any("Deletion stopped" in message for _, message in messages))

    def test_audit_record_excludes_credentials_and_private_target(self):
        workspace = WorkspaceDeletionPreview(
            id="ws-1",
            name="Workspace One",
            managed_private_endpoints=(),
        )
        endpoint = ManagedPrivateEndpoint("mpe-1", "Key Vault", "Approved")

        with application.app.test_request_context(headers={
            "X-MS-CLIENT-PRINCIPAL-NAME": "operator@example.com",
            "Authorization": "Bearer hidden-token",
        }):
            with self.assertLogs(application.app.logger, level="INFO") as captured:
                application.workspace_deletion_audit(
                    "managed_private_endpoint_deleted", workspace, endpoint, 200
                )

        log_output = " ".join(captured.output)
        self.assertIn("operator@example.com", log_output)
        self.assertIn('"http_status": 200', log_output)
        self.assertNotIn("hidden-token", log_output)
        self.assertNotIn("targetPrivateLinkResourceId", log_output)


if __name__ == "__main__":
    unittest.main()