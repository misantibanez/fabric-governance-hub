from dataclasses import asdict, dataclass
import re

import requests


AZURE_RESOURCE_ID_PATTERN = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/([^/]+)/([^/]+)/([^/]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MpeTarget:
    name: str
    setting_name: str
    resource_id: str
    resource_type: str
    subresource_type: str


class MpeValidationError(ValueError):
    def __init__(self, messages):
        super().__init__(" ".join(messages))
        self.messages = messages


MPE_DEFINITIONS = {
    "key_vault": {
        "name": "Key Vault",
        "setting_name": "mpe_keyvault_resource_id",
        "resource_type": "Microsoft.KeyVault/vaults",
        "subresource_type": "vault",
        "api_version": "2023-07-01",
    },
    "cognitive_services": {
        "name": "Cognitive Services",
        "setting_name": "mpe_cognitive_services_resource_id",
        "resource_type": "Microsoft.CognitiveServices/accounts",
        "subresource_type": "account",
        "api_version": "2024-10-01",
    },
}


def _validate_resource_id(resource_id, definition):
    match = AZURE_RESOURCE_ID_PATTERN.fullmatch(resource_id)
    if not match:
        return (
            f"{definition['name']} setting `{definition['setting_name']}` must be a "
            f"complete Azure resource ID for {definition['resource_type']}."
        )

    actual_type = f"{match.group(1)}/{match.group(2)}"
    if actual_type.lower() != definition["resource_type"].lower():
        return (
            f"{definition['name']} setting `{definition['setting_name']}` references "
            f"{actual_type}; expected {definition['resource_type']}."
        )
    return None


def _arm_error(definition, status_code):
    setting_name = definition["setting_name"]
    if status_code == 404:
        return f"{definition['name']} setting `{setting_name}` references a resource that does not exist."
    if status_code in (401, 403):
        return (
            f"{definition['name']} setting `{setting_name}` cannot be verified with your Azure permissions."
        )
    return (
        f"{definition['name']} setting `{setting_name}` could not be verified by Azure "
        f"(HTTP {status_code})."
    )


def validate_mpe_configuration(settings, include_cognitive_services, azure_headers, request_get):
    selected_types = ["key_vault"]
    if include_cognitive_services:
        selected_types.append("cognitive_services")

    errors = []
    targets = []
    for selected_type in selected_types:
        definition = MPE_DEFINITIONS[selected_type]
        resource_id = str(settings.get(definition["setting_name"], "")).strip().rstrip("/")
        if not resource_id:
            errors.append(
                f"{definition['name']} setting `{definition['setting_name']}` is required."
            )
            continue

        resource_id_error = _validate_resource_id(resource_id, definition)
        if resource_id_error:
            errors.append(resource_id_error)
            continue

        try:
            response = request_get(
                f"https://management.azure.com{resource_id}",
                headers=azure_headers,
                params={"api-version": definition["api_version"]},
                timeout=15,
            )
        except requests.RequestException:
            errors.append(
                f"{definition['name']} setting `{definition['setting_name']}` could not be "
                "verified because Azure Resource Manager is unavailable."
            )
            continue
        if response.status_code != 200:
            errors.append(_arm_error(definition, response.status_code))
            continue

        actual_type = str(response.json().get("type", ""))
        if actual_type.lower() != definition["resource_type"].lower():
            errors.append(
                f"{definition['name']} setting `{definition['setting_name']}` resolved to "
                f"{actual_type or 'an unknown resource type'}; expected {definition['resource_type']}."
            )
            continue

        try:
            private_link_response = request_get(
                f"https://management.azure.com{resource_id}/privateLinkResources",
                headers=azure_headers,
                params={"api-version": definition["api_version"]},
                timeout=15,
            )
        except requests.RequestException:
            errors.append(
                f"{definition['name']} private-link configuration could not be verified because "
                "Azure Resource Manager is unavailable."
            )
            continue
        if private_link_response.status_code != 200:
            errors.append(_arm_error(definition, private_link_response.status_code))
            continue
        group_ids = {
            str(item.get("properties", {}).get("groupId", "")).lower()
            for item in private_link_response.json().get("value", [])
        }
        if definition["subresource_type"].lower() not in group_ids:
            errors.append(
                f"{definition['name']} does not expose the required private-link subresource "
                f"`{definition['subresource_type']}`."
            )
            continue

        targets.append(MpeTarget(
            name=definition["name"],
            setting_name=definition["setting_name"],
            resource_id=resource_id,
            resource_type=definition["resource_type"],
            subresource_type=definition["subresource_type"],
        ))

    if errors:
        raise MpeValidationError(errors)
    return tuple(targets)


def mpe_audit_record(targets):
    return [asdict(target) for target in targets]