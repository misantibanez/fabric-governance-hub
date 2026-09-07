from dataclasses import dataclass
import re

import requests


SETTING_NAME = "log_analytics_workspace_resource_id"
RESOURCE_TYPE = "Microsoft.OperationalInsights/workspaces"
API_VERSION = "2023-09-01"
RESOURCE_ID_PATTERN = re.compile(
    r"^/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
    r"Microsoft\.OperationalInsights/workspaces/([^/]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkspaceMonitoringConfiguration:
    resource_id: str
    subscription_id: str
    resource_group: str
    workspace_name: str

    def to_power_bi_payload(self):
        return {
            "subscriptionId": self.subscription_id,
            "resourceGroup": self.resource_group,
            "resourceName": self.workspace_name,
        }


class MonitoringValidationError(ValueError):
    pass


def validate_monitoring_configuration(settings, azure_headers, request_get):
    resource_id = str(settings.get(SETTING_NAME, "")).strip().rstrip("/")
    if not resource_id:
        raise MonitoringValidationError(
            f"Workspace monitoring setting `{SETTING_NAME}` is required."
        )

    match = RESOURCE_ID_PATTERN.fullmatch(resource_id)
    if not match:
        raise MonitoringValidationError(
            f"Workspace monitoring setting `{SETTING_NAME}` must be a complete Azure "
            f"resource ID for {RESOURCE_TYPE}."
        )

    try:
        response = request_get(
            f"https://management.azure.com{resource_id}",
            headers=azure_headers,
            params={"api-version": API_VERSION},
            timeout=15,
        )
    except requests.RequestException as error:
        raise MonitoringValidationError(
            "The Log Analytics workspace could not be verified because Azure Resource "
            "Manager is unavailable."
        ) from error

    if response.status_code == 404:
        raise MonitoringValidationError(
            "The configured Log Analytics workspace does not exist."
        )
    if response.status_code in (401, 403):
        raise MonitoringValidationError(
            "The configured Log Analytics workspace cannot be verified with your Azure permissions."
        )
    if response.status_code != 200:
        raise MonitoringValidationError(
            "The configured Log Analytics workspace could not be verified by Azure "
            f"(HTTP {response.status_code})."
        )

    actual_type = str(response.json().get("type", ""))
    if actual_type.lower() != RESOURCE_TYPE.lower():
        raise MonitoringValidationError(
            "The workspace monitoring setting resolved to "
            f"{actual_type or 'an unknown resource type'}; expected {RESOURCE_TYPE}."
        )

    return WorkspaceMonitoringConfiguration(
        resource_id=resource_id,
        subscription_id=match.group(1),
        resource_group=match.group(2),
        workspace_name=match.group(3),
    )