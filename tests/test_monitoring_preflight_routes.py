import os
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch

os.environ.setdefault("FABRIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")

import app as application
from monitoring_validation import (
    PROVIDER_FABRIC,
    MonitoringValidationError,
    FabricWorkspaceMonitoringConfiguration,
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

    @patch.object(application, "fetch_capacities_admin", return_value=[])
    @patch.object(application, "fetch_capacities", return_value=[])
    @patch.object(application, "fetch_domains", return_value=[])
    @patch.object(application, "fetch_tags", return_value=[])
    @patch.object(application, "fetch_connections", return_value=[])
    @patch.object(application, "get_powerbi_headers", return_value={})
    @patch.object(application, "get_headers", return_value={})
    @patch.object(application, "load_settings", return_value=application.DEFAULT_SETTINGS)
    def test_create_workspace_form_shows_creation_progress(
        self,
        _load_settings,
        _get_headers,
        _get_powerbi_headers,
        _fetch_connections,
        _fetch_tags,
        _fetch_domains,
        _fetch_capacities,
        _fetch_capacities_admin,
    ):
        response = self.client.get("/create-workspace-form")

        self.assertEqual(200, response.status_code)
        self.assertIn(b'id="creation-overlay"', response.data)
        self.assertIn(b'id="creation-stage"', response.data)
        self.assertIn(b"Configuring workspace monitoring", response.data)

    @patch.object(application.requests, "post")
    @patch.object(application, "preflight_mpe_configuration", return_value=())
    @patch.object(application, "preflight_monitoring_selection")
    @patch.object(application, "get_powerbi_headers", return_value={})
    @patch.object(application, "load_settings", return_value={})
    def test_missing_monitoring_setting_blocks_before_workspace_creation(
        self,
        _load_settings,
        _get_powerbi_headers,
        monitoring_preflight,
        _mpe_preflight,
        post,
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

    @patch.object(application, "preflight_mpe_configuration", return_value=())
    @patch.object(application, "get_powerbi_headers", return_value={})
    @patch.object(application, "load_settings", return_value={
        **application.DEFAULT_SETTINGS,
        "workspace_monitoring_required": True,
    })
    def test_required_monitoring_blocks_developer_job_before_creation(
        self, _load_settings, _get_powerbi_headers, _mpe_preflight
    ):
        response = self.client.post(
            "/create-developer-workspaces",
            data={
                "main_workspace_id": "main-workspace",
                "dev_count": "0",
                "monitoring_provider": "none",
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])
        self.assertIn("required", response.get_json()["error"])
        self.assertIn("#workspace-monitoring", response.get_json()["settings_url"])
        self.assertEqual({}, application._dev_jobs)

    @patch.object(application.requests, "patch")
    @patch.object(application.requests, "post")
    def test_fabric_monitoring_creates_eventhouse_then_enables_ingestion(
        self, request_post, request_patch
    ):
        request_post.return_value.status_code = 200
        request_post.return_value.json.return_value = {
            "ingestionState": "Disabled",
            "artifact": {
                "artifactType": "KustoEventHouse",
                "systemArtifactType": "PlatformMonitoring",
            },
        }
        request_patch.return_value.status_code = 200
        request_patch.return_value.json.return_value = {
            "ingestionState": "Enabled"
        }
        configuration = FabricWorkspaceMonitoringConfiguration(
            api_base_url=(
                "https://wabi-west-us3-a-primary-redirect.analysis.windows.net"
            )
        )

        errors = application.configure_fabric_workspace_monitoring(
            "workspace-id", configuration, {"Authorization": "Bearer power-bi"}
        )

        self.assertEqual([], errors)
        request_post.assert_called_once_with(
            "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/"
            "metadata/platformMonitoring/workspace/workspace-id",
            headers={
                "Authorization": "Bearer power-bi",
                "Content-Type": "application/json",
                "ActivityId": ANY,
                "RequestId": ANY,
                "X-PowerBI-HostEnv": "Power BI Web App",
            },
            json={"artifactType": "KustoDatabase", "workloadPayload": "{}"},
            timeout=120,
        )
        request_patch.assert_called_once_with(
            "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/"
            "metadata/platformMonitoring/workspace/workspace-id"
            "?calledOnDatabaseCreation=true",
            headers={
                "Authorization": "Bearer power-bi",
                "Content-Type": "application/json",
                "ActivityId": ANY,
                "RequestId": ANY,
                "X-PowerBI-HostEnv": "Power BI Web App",
            },
            json={"ingestionState": "Enabled"},
            timeout=120,
        )

    @patch.object(application.requests, "patch")
    @patch.object(application.requests, "post")
    def test_fabric_monitoring_reports_enable_failure_without_success(
        self, request_post, request_patch
    ):
        request_post.return_value.status_code = 200
        request_post.return_value.json.return_value = {
            "artifact": {
                "artifactType": "KustoEventHouse",
                "systemArtifactType": "PlatformMonitoring",
            }
        }
        request_patch.return_value.status_code = 403
        request_patch.return_value.text = "Forbidden"

        errors = application.configure_fabric_workspace_monitoring(
            "workspace-id",
            FabricWorkspaceMonitoringConfiguration(
                api_base_url="https://wabi.example.analysis.windows.net"
            ),
            {"Authorization": "Bearer power-bi"},
        )

        self.assertEqual(1, len(errors))
        self.assertIn("created, but logging could not be enabled", errors[0])
        self.assertIn("Workspace settings > Monitoring", errors[0])

    @patch.object(application.time, "sleep")
    @patch.object(application.requests, "patch")
    @patch.object(application.requests, "post")
    def test_fabric_monitoring_retries_artifact_operation_conflict(
        self, request_post, request_patch, sleep
    ):
        request_post.return_value.status_code = 200
        request_post.return_value.json.return_value = {
            "artifact": {
                "artifactType": "KustoEventHouse",
                "systemArtifactType": "PlatformMonitoring",
            }
        }
        conflict = SimpleNamespace(
            status_code=409,
            text="ArtifactOperationConflict",
            json=lambda: {
                "error": {
                    "code": "ArtifactOperationConflict",
                    "pbi.error": {"code": "ArtifactOperationConflict"},
                }
            },
        )
        enabled = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"ingestionState": "Enabled"},
        )
        request_patch.side_effect = [conflict, conflict, enabled]

        errors = application.configure_fabric_workspace_monitoring(
            "workspace-id",
            FabricWorkspaceMonitoringConfiguration(
                api_base_url="https://wabi.example.analysis.windows.net"
            ),
            {"Authorization": "Bearer power-bi"},
        )

        self.assertEqual([], errors)
        self.assertEqual(3, request_patch.call_count)
        self.assertEqual([unittest.mock.call(1), unittest.mock.call(2)], sleep.call_args_list)

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
    def test_create_form_shows_exclusive_required_monitoring_options(
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
        self.assertIn(b'value="log_analytics" required', response.data)
        self.assertIn(b'value="fabric_workspace_monitoring" required', response.data)
        self.assertNotIn(b'value="none"', response.data)
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
                "workspace_monitoring_required": "1",
                "log_analytics_workspace_resource_id": f"  {LOG_ANALYTICS_ID}  ",
                "fabric_monitoring_api_base_url": (
                    "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/"
                ),
            },
        )

        self.assertEqual(302, response.status_code)
        saved_settings = save.call_args.args[0]
        self.assertEqual(
            LOG_ANALYTICS_ID,
            saved_settings["log_analytics_workspace_resource_id"],
        )
        self.assertTrue(saved_settings["workspace_monitoring_required"])
        self.assertEqual(
            "https://wabi-west-us3-a-primary-redirect.analysis.windows.net",
            saved_settings["fabric_monitoring_api_base_url"],
        )
        self.assertEqual('"1"', save.call_args.args[1])

    @patch.object(application._settings_repository, "load")
    def test_settings_page_renders_monitoring_resource_id(self, load):
        load.return_value = SimpleNamespace(
            settings={
                **application.DEFAULT_SETTINGS,
                "log_analytics_workspace_resource_id": LOG_ANALYTICS_ID,
                "fabric_monitoring_api_base_url": (
                    "https://wabi-west-us3-a-primary-redirect.analysis.windows.net"
                ),
            },
            etag='"1"',
        )

        response = self.client.get("/settings")

        self.assertEqual(200, response.status_code)
        self.assertIn(b'id="workspace-monitoring"', response.data)
        self.assertIn(LOG_ANALYTICS_ID.encode(), response.data)
        self.assertIn(b"wabi-west-us3-a-primary-redirect", response.data)


if __name__ == "__main__":
    unittest.main()