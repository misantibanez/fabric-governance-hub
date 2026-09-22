import unittest

from permission_audit import (
    ResolvedPrincipal,
    audit_principal_access,
    fetch_effective_principals,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class PermissionAuditTests(unittest.TestCase):
    def test_user_inherits_workspace_and_onelake_access_from_group(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User", "ada@example.com")

        def request_get(url, **_kwargs):
            if "transitiveMemberOf" in url:
                return FakeResponse(200, {"value": [{"id": "group-1", "displayName": "Analysts"}]})
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": [{
                    "principal": {"id": "group-1", "type": "Group"},
                    "role": "Viewer",
                }]})
            if url.endswith("/items"):
                return FakeResponse(200, {"value": [{
                    "id": "lakehouse-1", "displayName": "Sales", "type": "Lakehouse"
                }]})
            if url.endswith("/dataAccessRoles"):
                return FakeResponse(200, {"value": [{
                    "name": "SalesReaders",
                    "members": {"microsoftEntraMembers": [{"objectId": "group-1"}]},
                    "decisionRules": [{
                        "effect": "Permit",
                        "permission": [
                            {"attributeName": "Action", "attributeValueIncludedIn": ["Read"]},
                            {"attributeName": "Path", "attributeValueIncludedIn": ["Tables/Sales"]},
                        ],
                    }],
                }]})
            raise AssertionError(url)

        effective = fetch_effective_principals(principal, {}, request_get)
        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Analytics"}],
            {},
            request_get,
        )

        self.assertEqual(1, result["workspaceCount"])
        self.assertEqual(1, result["lakehouseCount"])
        self.assertEqual("Viewer", result["workspaces"][0]["roles"][0]["role"])
        lakehouse_role = result["workspaces"][0]["lakehouses"][0]["roles"][0]
        self.assertEqual("SalesReaders", lakehouse_role["role"])
        self.assertEqual(["Tables/Sales"], lakehouse_role["paths"])
        self.assertFalse(lakehouse_role["direct"])

    def test_direct_onelake_access_is_returned_without_workspace_role(self):
        principal = ResolvedPrincipal("group-1", "External Readers", "Group")
        effective = {
            "group-1": {
                "id": "group-1",
                "displayName": "External Readers",
                "type": "Group",
                "direct": True,
            }
        }

        def request_get(url, **_kwargs):
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": []})
            if url.endswith("/items"):
                return FakeResponse(200, {"value": [{
                    "id": "lakehouse-1", "displayName": "Shared", "type": "Lakehouse"
                }]})
            if url.endswith("/dataAccessRoles"):
                return FakeResponse(200, {"value": [{
                    "name": "External",
                    "members": {"microsoftEntraMembers": [{"objectId": "group-1"}]},
                    "decisionRules": [],
                }]})
            raise AssertionError(url)

        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Analytics"}],
            {},
            request_get,
        )

        self.assertEqual([], result["workspaces"][0]["roles"])
        self.assertEqual("External", result["workspaces"][0]["lakehouses"][0]["roles"][0]["role"])

    def test_partial_api_failure_is_reported_without_hiding_workspace_access(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User")
        effective = {
            "user-1": {
                "id": "user-1", "displayName": "Ada", "type": "User", "direct": True
            }
        }

        def request_get(url, **_kwargs):
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": [{
                    "principal": {"id": "user-1", "type": "User"}, "role": "Member"
                }]})
            if url.endswith("/items"):
                return FakeResponse(403, text="Forbidden")
            raise AssertionError(url)

        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Restricted"}],
            {},
            request_get,
        )

        self.assertEqual(1, result["workspaceCount"])
        self.assertEqual(1, len(result["warnings"]))
        self.assertIn("could not be fully inspected", result["warnings"][0])

    def test_fabric_item_member_only_inherits_from_current_lakehouse(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User")
        effective = {
            "user-1": {
                "id": "user-1", "displayName": "Ada", "type": "User", "direct": True
            }
        }

        def request_get(url, **_kwargs):
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": [{
                    "principal": {"id": "user-1", "type": "User"}, "role": "Viewer"
                }]})
            if url.endswith("/items"):
                return FakeResponse(200, {"value": [{
                    "id": "lakehouse-1", "displayName": "Sales", "type": "Lakehouse"
                }]})
            if url.endswith("/dataAccessRoles"):
                return FakeResponse(200, {"value": [
                    {
                        "name": "CurrentItemReader",
                        "members": {"fabricItemMembers": [{
                            "sourcePath": "workspace-1/lakehouse-1", "itemAccess": ["ReadAll"]
                        }]},
                        "decisionRules": [],
                    },
                    {
                        "name": "OtherItemReader",
                        "members": {"fabricItemMembers": [{
                            "sourcePath": "workspace-1/lakehouse-2", "itemAccess": ["ReadAll"]
                        }]},
                        "decisionRules": [],
                    },
                ]})
            raise AssertionError(url)

        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Analytics"}],
            {},
            request_get,
        )

        roles = result["workspaces"][0]["lakehouses"][0]["roles"]
        self.assertEqual(["CurrentItemReader"], [role["role"] for role in roles])

    def test_configured_onelake_roles_do_not_imply_access_from_workspace_role(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User")
        effective = {
            "user-1": {
                "id": "user-1", "displayName": "Ada", "type": "User", "direct": True
            }
        }

        def request_get(url, **_kwargs):
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": [{
                    "principal": {"id": "user-1", "type": "User"}, "role": "Viewer"
                }]})
            if url.endswith("/items"):
                return FakeResponse(200, {"value": [{
                    "id": "lakehouse-1", "displayName": "Restricted", "type": "Lakehouse"
                }]})
            if url.endswith("/dataAccessRoles"):
                return FakeResponse(200, {"value": [{
                    "name": "OtherReaders",
                    "members": {"microsoftEntraMembers": [{"objectId": "other-group"}]},
                    "decisionRules": [],
                }]})
            raise AssertionError(url)

        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Analytics"}],
            {},
            request_get,
        )

        self.assertEqual(1, result["workspaceCount"])
        self.assertEqual(0, result["lakehouseCount"])

    def test_unsupported_and_stale_workspaces_are_silently_skipped(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User")
        effective = {
            "user-1": {
                "id": "user-1", "displayName": "Ada", "type": "User", "direct": True
            }
        }
        requested_urls = []

        def request_get(url, **_kwargs):
            requested_urls.append(url)
            return FakeResponse(404, {
                "requestId": "request-1",
                "errorCode": "WorkspaceNotFound",
                "message": "The provided workspace was not found",
            })

        result = audit_principal_access(
            principal,
            effective,
            [
                {"id": "personal", "displayName": "My workspace", "type": "PersonalGroup"},
                {"id": "deleted", "displayName": "Old", "type": "Workspace", "state": "Deleted"},
                {"id": "stale", "displayName": "Stale", "type": "Workspace"},
            ],
            {},
            request_get,
        )

        self.assertEqual(1, len(requested_urls))
        self.assertIn("stale", requested_urls[0])
        self.assertEqual([], result["workspaces"])
        self.assertEqual([], result["warnings"])

    def test_unavailable_onelake_roles_do_not_imply_default_access(self):
        principal = ResolvedPrincipal("user-1", "Ada", "User")
        effective = {
            "user-1": {
                "id": "user-1", "displayName": "Ada", "type": "User", "direct": True
            }
        }

        def request_get(url, **_kwargs):
            if url.endswith("/roleAssignments"):
                return FakeResponse(200, {"value": [{
                    "principal": {"id": "user-1", "type": "User"}, "role": "Viewer"
                }]})
            if url.endswith("/items"):
                return FakeResponse(200, {"value": [{
                    "id": "lakehouse-1", "displayName": "Restricted", "type": "Lakehouse"
                }]})
            if url.endswith("/dataAccessRoles"):
                return FakeResponse(403, {
                    "error": {"errorCode": "InsufficientPrivileges", "message": "Forbidden"}
                })
            raise AssertionError(url)

        result = audit_principal_access(
            principal,
            effective,
            [{"id": "workspace-1", "displayName": "Analytics", "type": "Workspace"}],
            {},
            request_get,
        )

        self.assertEqual(1, result["workspaceCount"])
        self.assertEqual(0, result["lakehouseCount"])
        self.assertEqual(1, len(result["warnings"]))


if __name__ == "__main__":
    unittest.main()