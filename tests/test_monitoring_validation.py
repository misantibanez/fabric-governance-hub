import unittest

import requests

from monitoring_validation import (
    PROVIDER_FABRIC,
    PROVIDER_LOG_ANALYTICS,
    PROVIDER_NONE,
    MonitoringValidationError,
    validate_monitoring_configuration,
    validate_monitoring_selection,
)


LOG_ANALYTICS_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/governance/providers/Microsoft.OperationalInsights/"
    "workspaces/governance-logs"
)


class FakeResponse:
    def __init__(self, status_code, resource_type=None):
        self.status_code = status_code
        self.resource_type = resource_type

    def json(self):
        return {"type": self.resource_type} if self.resource_type else {}


class MonitoringValidationTests(unittest.TestCase):
    def test_optional_policy_allows_no_monitoring(self):
        selection = validate_monitoring_selection(
            {"workspace_monitoring_required": False},
            PROVIDER_NONE,
            {},
            lambda *args, **kwargs: None,
            {},
        )

        self.assertEqual(PROVIDER_NONE, selection.provider)
        self.assertIsNone(selection.configuration)

    def test_required_policy_rejects_no_monitoring(self):
        with self.assertRaisesRegex(MonitoringValidationError, "required"):
            validate_monitoring_selection(
                {"workspace_monitoring_required": True},
                PROVIDER_NONE,
                {},
                lambda *args, **kwargs: None,
                {},
            )

    def test_rejects_unknown_provider(self):
        with self.assertRaisesRegex(MonitoringValidationError, "valid"):
            validate_monitoring_selection(
                {}, "both", {}, lambda *args, **kwargs: None, {}
            )

    def test_validates_fabric_cluster_and_power_bi_token(self):
        settings = {
            "fabric_monitoring_api_base_url": (
                "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/"
            )
        }
        selection = validate_monitoring_selection(
            settings,
            PROVIDER_FABRIC,
            {},
            lambda *args, **kwargs: None,
            {"Authorization": "Bearer token"},
        )

        self.assertEqual(PROVIDER_FABRIC, selection.provider)
        self.assertEqual(
            "https://wabi-west-us3-a-primary-redirect.analysis.windows.net",
            selection.configuration.api_base_url,
        )

        for invalid_url in ("", "http://example.com", "https://example.com/path"):
            with self.subTest(invalid_url=invalid_url):
                with self.assertRaisesRegex(MonitoringValidationError, "cluster URL"):
                    validate_monitoring_selection(
                        {"fabric_monitoring_api_base_url": invalid_url},
                        PROVIDER_FABRIC,
                        {},
                        lambda *args, **kwargs: None,
                        {"Authorization": "Bearer token"},
                    )

    def test_log_analytics_selection_uses_arm_validation(self):
        selection = validate_monitoring_selection(
            {"log_analytics_workspace_resource_id": LOG_ANALYTICS_ID},
            PROVIDER_LOG_ANALYTICS,
            {},
            lambda *args, **kwargs: FakeResponse(
                200, "Microsoft.OperationalInsights/workspaces"
            ),
            {},
        )

        self.assertEqual(PROVIDER_LOG_ANALYTICS, selection.provider)
        self.assertEqual("governance-logs", selection.configuration.workspace_name)

    def test_requires_workspace_setting(self):
        with self.assertRaisesRegex(MonitoringValidationError, "required"):
            validate_monitoring_configuration({}, {}, lambda *args, **kwargs: None)

    def test_rejects_malformed_id_before_arm_lookup(self):
        calls = []

        with self.assertRaisesRegex(MonitoringValidationError, "complete Azure resource ID"):
            validate_monitoring_configuration(
                {"log_analytics_workspace_resource_id": "not-an-id"},
                {},
                lambda *args, **kwargs: calls.append((args, kwargs)),
            )

        self.assertEqual([], calls)

    def test_reports_missing_and_unavailable_resources(self):
        with self.assertRaisesRegex(MonitoringValidationError, "does not exist"):
            validate_monitoring_configuration(
                {"log_analytics_workspace_resource_id": LOG_ANALYTICS_ID},
                {},
                lambda *args, **kwargs: FakeResponse(404),
            )

        def unavailable(*args, **kwargs):
            raise requests.ConnectionError("reset")

        with self.assertRaisesRegex(MonitoringValidationError, "unavailable"):
            validate_monitoring_configuration(
                {"log_analytics_workspace_resource_id": LOG_ANALYTICS_ID},
                {},
                unavailable,
            )

    def test_returns_power_bi_configuration_after_arm_validation(self):
        calls = []

        def lookup(url, headers, params, timeout):
            calls.append((url, headers, params, timeout))
            return FakeResponse(200, "Microsoft.OperationalInsights/workspaces")

        configuration = validate_monitoring_configuration(
            {"log_analytics_workspace_resource_id": f"{LOG_ANALYTICS_ID}/"},
            {"Authorization": "Bearer hidden"},
            lookup,
        )

        self.assertEqual(LOG_ANALYTICS_ID, configuration.resource_id)
        self.assertEqual(
            {
                "subscriptionId": "00000000-0000-0000-0000-000000000000",
                "resourceGroup": "governance",
                "resourceName": "governance-logs",
            },
            configuration.to_power_bi_payload(),
        )
        self.assertEqual("2023-09-01", calls[0][2]["api-version"])
        self.assertEqual(15, calls[0][3])


if __name__ == "__main__":
    unittest.main()