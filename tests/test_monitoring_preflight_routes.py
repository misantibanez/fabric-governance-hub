import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("FABRIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")

import app as application
from monitoring_validation import (
    MonitoringValidationError,
    WorkspaceMonitoringConfiguration,
)


LOG_ANALYTICS_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/governance/providers/Microsoft.OperationalInsights/"
    "workspaces/governance-logs"
)


class MonitoringPreflightRouteTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    @patch.object(application.requests, "post")
    @patch.object(application, "preflight_mpe_configuration", return_value=())
    @patch.object(application, "preflight_monitoring_configuration")
    @patch.object(application, "load_settings", return_value={})
    def test_missing_monitoring_setting_blocks_before_workspace_creation(
        self, _load_settings, monitoring_preflight, _mpe_preflight, post
    ):
        monitoring_preflight.side_effect = MonitoringValidationError(
            "Workspace monitoring setting is required."
        )

        response = self.client.post(
            "/create-workspace",
            data={
                "name": "blocked-workspace",
                "capacity_id": "capacity",
                "la_subscription_id": "attacker-subscription",
                "la_resource_group": "attacker-resource-group",
                "la_workspace_name": "attacker-workspace",
            },
        )

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/create-workspace-form"))
        post.assert_not_called()
        with self.client.session_transaction() as session:
            messages = session.get("_flashes", [])
        self.assertIn(
            ("monitoring-error", "Workspace monitoring setting is required."),
            messages,
        )

    @patch.object(application.requests, "patch")
    def test_monitoring_patch_uses_validated_configuration(self, request_patch):
        request_patch.return_value.status_code = 200
        configuration = WorkspaceMonitoringConfiguration(
            resource_id=LOG_ANALYTICS_ID,
            subscription_id="validated-subscription",
            resource_group="validated-resource-group",
            workspace_name="validated-workspace",
        )

        errors = application.configure_workspace_monitoring(
            "workspace-id",
            configuration,
            {"Authorization": "Bearer power-bi"},
        )

        self.assertEqual([], errors)
        self.assertEqual(
            {
                "logAnalyticsWorkspace": {
                    "subscriptionId": "validated-subscription",
                    "resourceGroup": "validated-resource-group",
                    "resourceName": "validated-workspace",
                }
            },
            request_patch.call_args.kwargs["json"],
        )

    @patch.object(application, "load_settings")
    @patch.object(application, "fetch_connections", return_value=[])
    @patch.object(application, "fetch_tags", return_value=[])
    @patch.object(application, "fetch_domains", return_value=[])
    @patch.object(application, "fetch_capacities_admin", return_value=[])
    @patch.object(application, "fetch_capacities", return_value=[])
    @patch.object(application, "get_powerbi_headers", return_value={})
    @patch.object(application, "get_headers", return_value={})
    def test_create_form_shows_mandatory_centralized_monitoring(
        self,
        _get_headers,
        _get_powerbi_headers,
        _fetch_capacities,
        _fetch_capacities_admin,
        _fetch_domains,
        _fetch_tags,
        _fetch_connections,
        load_settings,
    ):
        load_settings.return_value = {
            **application.DEFAULT_SETTINGS,
            "log_analytics_workspace_resource_id": LOG_ANALYTICS_ID,
        }
        with self.client.session_transaction() as session:
            session["_flashes"] = [
                ("monitoring-error", "Workspace monitoring setting is required.")
            ]

        response = self.client.get("/create-workspace-form")

        self.assertEqual(200, response.status_code)
        self.assertIn(b'id="workspace-monitoring"', response.data)
        self.assertIn(b"governance-logs", response.data)
        self.assertIn(b'type="checkbox" checked disabled', response.data)
        self.assertIn(b'href="/settings#workspace-monitoring"', response.data)
        self.assertNotIn(b'name="la_subscription_id"', response.data)
        self.assertNotIn(b'name="la_resource_group"', response.data)
        self.assertNotIn(b'name="la_workspace_name"', response.data)

    @patch.object(application._settings_repository, "save")
    def test_settings_post_persists_log_analytics_resource_id(self, save):
        response = self.client.post(
            "/settings",
            data={
                "settings_etag": '"1"',
                "log_analytics_workspace_resource_id": f"  {LOG_ANALYTICS_ID}  ",
            },
        )

        self.assertEqual(302, response.status_code)
        saved_settings = save.call_args.args[0]
        self.assertEqual(
            LOG_ANALYTICS_ID,
            saved_settings["log_analytics_workspace_resource_id"],
        )
        self.assertEqual('"1"', save.call_args.args[1])

    @patch.object(application._settings_repository, "load")
    def test_settings_page_renders_monitoring_resource_id(self, load):
        load.return_value = SimpleNamespace(
            settings={
                **application.DEFAULT_SETTINGS,
                "log_analytics_workspace_resource_id": LOG_ANALYTICS_ID,
            },
            etag='"1"',
        )

        response = self.client.get("/settings")

        self.assertEqual(200, response.status_code)
        self.assertIn(b'id="workspace-monitoring"', response.data)
        self.assertIn(LOG_ANALYTICS_ID.encode(), response.data)


if __name__ == "__main__":
    unittest.main()