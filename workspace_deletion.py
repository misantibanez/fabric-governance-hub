from dataclasses import dataclass
import time
from urllib.parse import urlparse

import requests


FABRIC_API_ROOT = "https://api.fabric.microsoft.com/v1"


class WorkspaceDeletionError(RuntimeError):
    def __init__(self, message, completed_workspace_ids=()):
        super().__init__(message)
        self.completed_workspace_ids = tuple(completed_workspace_ids)


@dataclass(frozen=True)
class ManagedPrivateEndpoint:
    id: str
    name: str
    status: str


@dataclass(frozen=True)
class WorkspaceDeletionPreview:
    id: str
    name: str
    managed_private_endpoints: tuple
    already_absent: bool = False


def _response_detail(response):
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error") or {}
        detail = error.get("message") or payload.get("message")
        if detail:
            return str(detail)[:300]
    return (getattr(response, "text", "") or "unknown Fabric API error")[:300]


def _retry_after_seconds(response):
    try:
        return min(max(float(response.headers.get("Retry-After", "1")), 0), 10)
    except (AttributeError, TypeError, ValueError):
        return 1


def _request_with_throttle(method, url, headers, request_call, sleep, max_retries=2):
    for attempt in range(max_retries + 1):
        response = request_call(url, headers=headers, timeout=30)
        if response.status_code != 429 or attempt == max_retries:
            return response
        sleep(_retry_after_seconds(response))
    raise AssertionError("unreachable")


def _safe_continuation_uri(uri, workspace_id):
    parsed = urlparse(uri)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "api.fabric.microsoft.com"
        and parsed.path
        == f"/v1/workspaces/{workspace_id}/managedPrivateEndpoints"
    )


def list_managed_private_endpoints(
    workspace_id, fabric_headers, request_get=requests.get, sleep=time.sleep
):
    url = f"{FABRIC_API_ROOT}/workspaces/{workspace_id}/managedPrivateEndpoints"
    endpoints = []
    seen_urls = set()
    while url:
        if url in seen_urls or len(seen_urls) >= 100:
            raise WorkspaceDeletionError(
                f"Managed private endpoint pagination did not terminate for workspace {workspace_id}."
            )
        seen_urls.add(url)
        response = _request_with_throttle("GET", url, fabric_headers, request_get, sleep)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise WorkspaceDeletionError(
                f"Could not inspect managed private endpoints for workspace {workspace_id}: "
                f"{response.status_code} - {_response_detail(response)}"
            )
        payload = response.json()
        for item in payload.get("value", []):
            endpoint_id = str(item.get("id") or "").strip()
            if not endpoint_id:
                raise WorkspaceDeletionError(
                    f"Fabric returned a managed private endpoint without an ID for workspace {workspace_id}."
                )
            connection_state = item.get("connectionState") or {}
            endpoints.append(ManagedPrivateEndpoint(
                id=endpoint_id,
                name=str(item.get("name") or endpoint_id),
                status=str(
                    connection_state.get("status")
                    or item.get("provisioningState")
                    or "Unknown"
                ),
            ))
        continuation_uri = payload.get("continuationUri")
        if continuation_uri and not _safe_continuation_uri(continuation_uri, workspace_id):
            raise WorkspaceDeletionError(
                f"Fabric returned an invalid continuation URI for workspace {workspace_id}."
            )
        url = continuation_uri
    return tuple(endpoints)


def discover_workspace_deletions(
    workspace_ids, fabric_headers, request_get=requests.get, sleep=time.sleep
):
    previews = []
    for workspace_id in workspace_ids:
        workspace_url = f"{FABRIC_API_ROOT}/workspaces/{workspace_id}"
        response = _request_with_throttle(
            "GET", workspace_url, fabric_headers, request_get, sleep
        )
        if response.status_code == 404:
            previews.append(WorkspaceDeletionPreview(
                id=workspace_id,
                name=workspace_id,
                managed_private_endpoints=(),
                already_absent=True,
            ))
            continue
        if response.status_code != 200:
            raise WorkspaceDeletionError(
                f"Could not inspect workspace {workspace_id}: {response.status_code} - "
                f"{_response_detail(response)}"
            )
        workspace = response.json()
        endpoints = list_managed_private_endpoints(
            workspace_id, fabric_headers, request_get, sleep
        )
        if endpoints is None:
            previews.append(WorkspaceDeletionPreview(
                id=workspace_id,
                name=str(workspace.get("displayName") or workspace_id),
                managed_private_endpoints=(),
                already_absent=True,
            ))
            continue
        previews.append(WorkspaceDeletionPreview(
            id=workspace_id,
            name=str(workspace.get("displayName") or workspace_id),
            managed_private_endpoints=endpoints,
        ))
    return tuple(previews)


def _verify_endpoint_absent(
    workspace_id,
    endpoint_id,
    fabric_headers,
    request_get,
    sleep,
    verification_attempts,
):
    url = (
        f"{FABRIC_API_ROOT}/workspaces/{workspace_id}/managedPrivateEndpoints/{endpoint_id}"
    )
    for attempt in range(verification_attempts):
        response = _request_with_throttle("GET", url, fabric_headers, request_get, sleep)
        if response.status_code == 404:
            return
        if response.status_code != 200:
            raise WorkspaceDeletionError(
                f"Could not verify managed private endpoint {endpoint_id} in workspace "
                f"{workspace_id}: {response.status_code} - {_response_detail(response)}"
            )
        if attempt + 1 < verification_attempts:
            sleep(1)
    raise WorkspaceDeletionError(
        f"Managed private endpoint {endpoint_id} still exists in workspace {workspace_id}."
    )


def execute_workspace_deletions(
    workspace_ids,
    fabric_headers,
    request_get=requests.get,
    request_delete=requests.delete,
    sleep=time.sleep,
    verification_attempts=5,
    audit=None,
):
    previews = discover_workspace_deletions(
        workspace_ids, fabric_headers, request_get, sleep
    )
    completed = []
    for workspace in previews:
        if workspace.already_absent:
            completed.append(workspace.id)
            if audit:
                audit("workspace_already_absent", workspace, None, 404)
            continue
        try:
            for endpoint in workspace.managed_private_endpoints:
                url = (
                    f"{FABRIC_API_ROOT}/workspaces/{workspace.id}/managedPrivateEndpoints/"
                    f"{endpoint.id}"
                )
                response = _request_with_throttle(
                    "DELETE", url, fabric_headers, request_delete, sleep
                )
                if response.status_code not in (200, 404):
                    raise WorkspaceDeletionError(
                        f"Could not delete managed private endpoint {endpoint.name} from "
                        f"workspace {workspace.name}: {response.status_code} - "
                        f"{_response_detail(response)}"
                    )
                _verify_endpoint_absent(
                    workspace.id,
                    endpoint.id,
                    fabric_headers,
                    request_get,
                    sleep,
                    verification_attempts,
                )
                if audit:
                    audit(
                        "managed_private_endpoint_deleted",
                        workspace,
                        endpoint,
                        response.status_code,
                    )

            remaining = list_managed_private_endpoints(
                workspace.id, fabric_headers, request_get, sleep
            )
            if remaining:
                raise WorkspaceDeletionError(
                    f"Workspace {workspace.name} still has {len(remaining)} managed private "
                    "endpoint(s); the workspace was not deleted."
                )

            response = _request_with_throttle(
                "DELETE",
                f"{FABRIC_API_ROOT}/workspaces/{workspace.id}",
                fabric_headers,
                request_delete,
                sleep,
            )
            if response.status_code not in (200, 204, 404):
                raise WorkspaceDeletionError(
                    f"Could not delete workspace {workspace.name}: {response.status_code} - "
                    f"{_response_detail(response)}"
                )
            completed.append(workspace.id)
            if audit:
                audit("workspace_deleted", workspace, None, response.status_code)
        except WorkspaceDeletionError as error:
            raise WorkspaceDeletionError(str(error), completed) from error
    return tuple(completed)