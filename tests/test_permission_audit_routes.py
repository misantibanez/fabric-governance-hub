import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FABRIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")

import app as application
from permission_audit import ResolvedPrincipal


class PermissionAuditRouteTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    @patch.object(application, "get_graph_token")
    def test_empty_form_does_not_request_a_token(self, get_graph_token):
        response = self.client.get("/permission-audit")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Permission Audit", response.data)
        self.assertIn(b"Analyzing effective access...", response.data)
        self.assertIn(b'id="analysis-status"', response.data)
        get_graph_token.assert_not_called()

    @patch.object(application, "audit_principal_access")
    @patch.object(application, "fetch_workspaces_admin", return_value=[])
    @patch.object(application, "fetch_workspaces", return_value=[])
    @patch.object(application, "fetch_effective_principals", return_value={"user-1": {}})
    @patch.object(
        application,
        "resolve_audit_principal",
        return_value=ResolvedPrincipal("user-1", "Ada Lovelace", "User", "ada@example.com"),
    )
    @patch.object(application, "get_powerbi_headers", return_value={})
    @patch.object(application, "get_headers", return_value={})
    @patch.object(application, "get_graph_token", return_value="graph-token")
    def test_search_renders_workspace_and_onelake_access(
        self,
        _graph_token,
        _fabric_headers,
        _pbi_headers,
        _resolve,
        _effective,
        _fetch_workspaces,
        _fetch_workspaces_admin,
        audit,
    ):
        audit.return_value = {
            "principal": {
                "id": "user-1", "displayName": "Ada Lovelace", "type": "User",
                "userPrincipalName": "ada@example.com",
            },
            "effectivePrincipalCount": 2,
            "workspaceCount": 1,
            "lakehouseCount": 1,
            "warnings": [],
            "workspaces": [{
                "id": "workspace-1",
                "name": "Analytics",
                "roles": [{
                    "role": "Viewer", "sourceName": "Analysts", "direct": False,
                }],
                "lakehouses": [{
                    "id": "lakehouse-1",
                    "name": "Sales",
                    "workspaceInherited": True,
                    "roles": [{
                        "role": "SalesReaders", "actions": ["Read"],
                        "paths": ["Tables/Sales"], "sourceName": "Analysts",
                        "direct": False,
                    }],
                }],
            }],
        }

        response = self.client.get("/permission-audit?principal=ada%40example.com")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Ada Lovelace", response.data)
        self.assertIn(b"Analytics", response.data)
        self.assertIn(b"SalesReaders", response.data)
        self.assertIn(b"Tables/Sales", response.data)
        self.assertIn(b"Inherited", response.data)


if __name__ == "__main__":
    unittest.main()