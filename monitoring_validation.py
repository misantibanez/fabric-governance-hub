from dataclasses import dataclass
import re
from urllib.parse import urlparse

import requests


SETTING_NAME = "log_analytics_workspace_resource_id"
FABRIC_API_SETTING_NAME = "fabric_monitoring_api_base_url"
FABRIC_ENABLED_SETTING_NAME = "fabric_workspace_monitoring_enabled"
REQUIRED_SETTING_NAME = "workspace_monitoring_required"
PROVIDER_NONE = "none"
PROVIDER_LOG_ANALYTICS = "log_analytics"
PROVIDER_FABRIC = "fabric_workspace_monitoring"
VALID_PROVIDERS = {PROVIDER_NONE, PROVIDER_LOG_ANALYTICS, PROVIDER_FABRIC}
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


@dataclass(frozen=True)
class FabricWorkspaceMonitoringConfiguration:
    api_base_url: str


@dataclass(frozen=True)
class MonitoringSelection:
    provider: str
    configuration: object = None


class MonitoringValidationError(ValueError):
    pass


def monitoring_is_required(settings):
    value = settings.get(REQUIRED_SETTING_NAME, False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def fabric_monitoring_is_enabled(settings):
    value = settings.get(FABRIC_ENABLED_SETTING_NAME, False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def validate_monitoring_selection(
    settings, provider, azure_headers, request_get, power_bi_headers
):
    selected_provider = str(provider or PROVIDER_NONE).strip().lower()
    if selected_provider not in VALID_PROVIDERS:
        raise MonitoringValidationError("Select a valid workspace monitoring option.")
    if selected_provider == PROVIDER_NONE:
        if monitoring_is_required(settings):
            raise MonitoringValidationError(
                "Workspace monitoring is required. Select Log Analytics or Fabric "
                "Workspace Monitoring."
            )
        return MonitoringSelection(PROVIDER_NONE)
    if selected_provider == PROVIDER_LOG_ANALYTICS:
        return MonitoringSelection(
            PROVIDER_LOG_ANALYTICS,
            validate_monitoring_configuration(settings, azure_headers, request_get),
        )
    if not fabric_monitoring_is_enabled(settings):
        raise MonitoringValidationError(
            "Fabric Workspace Monitoring is temporarily unavailable until Fabric "
            "provides an official API. Select Log Analytics instead."
        )

    api_base_url = str(settings.get(FABRIC_API_SETTING_NAME, "")).strip().rstrip("/")
    parsed_url = urlparse(api_base_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or not parsed_url.hostname.lower().endswith(".analysis.windows.net")
        or parsed_url.path not in ("", "/")
    ):
        raise MonitoringValidationError(
            f"Workspace monitoring setting `{FABRIC_API_SETTING_NAME}` must be an "
            "HTTPS analysis.windows.net cluster URL."
        )
    if not str(power_bi_headers.get("Authorization", "")).startswith("Bearer "):
        raise MonitoringValidationError(
            "Fabric Workspace Monitoring requires a Power BI access token. Sign in "
            "again and retry."
        )
    return MonitoringSelection(
        PROVIDER_FABRIC,
        FabricWorkspaceMonitoringConfiguration(api_base_url=api_base_url),
    )


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