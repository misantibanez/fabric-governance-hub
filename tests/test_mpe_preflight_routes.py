import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FABRIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")

import app as application
from mpe_validation import MpeTarget


class MpePreflightRouteTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        application._dev_jobs.clear()
        self.client = application.app.test_client()

    @patch.object(application.requests, "post")
    @patch.object(application, "load_settings", return_value={})
    @patch.object(application, "get_azure_token", return_value="azure-token")
    def test_standard_workspace_preflight_blocks_before_creation(
        self, _get_azure_token, _load_settings, post
    ):
        response = self.client.post(
            "/create-workspace",
            data={"name": "blocked-workspace", "capacity_id": "capacity"},
        )

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/create-workspace-form"))
        post.assert_not_called()
        with self.client.session_transaction() as session:
            messages = session.get("_flashes", [])
        self.assertTrue(any("mpe_keyvault_resource_id" in message for _, message in messages))

    @patch.object(application.requests, "post")
    @patch.object(application, "load_settings", return_value={})
    @patch.object(application, "get_azure_token", return_value="azure-token")
    def test_developer_workspace_preflight_blocks_before_job_creation(
        self, _get_azure_token, _load_settings, post
    ):
        response = self.client.post(
            "/create-developer-workspaces",
            data={"main_workspace_id": "main-workspace", "dev_count": "0"},
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])
        self.assertIn("#managed-private-endpoints", response.get_json()["settings_url"])
        self.assertEqual({}, application._dev_jobs)
        post.assert_not_called()

    @patch.object(application.requests, "post")
    def test_mpe_creation_uses_validated_target_snapshot(self, post):
        post.return_value.status_code = 201
        target = MpeTarget(
            name="Key Vault",
            setting_name="mpe_keyvault_resource_id",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv",
            resource_type="Microsoft.KeyVault/vaults",
            subresource_type="vault",
        )

        errors = application.create_managed_private_endpoints(
            "workspace-id", "workspace-name", (target,), {"Authorization": "Bearer fabric"}
        )

        self.assertEqual([], errors)
        self.assertEqual(
            target.resource_id,
            post.call_args.kwargs["json"]["targetPrivateLinkResourceId"],
        )
        self.assertEqual("vault", post.call_args.kwargs["json"]["targetSubresourceType"])


if __name__ == "__main__":
    unittest.main()