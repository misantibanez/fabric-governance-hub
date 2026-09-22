from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse


FABRIC_API_ROOT = "https://api.fabric.microsoft.com/v1"
GRAPH_API_ROOT = "https://graph.microsoft.com/v1.0"
ALLOWED_API_HOSTS = {"api.fabric.microsoft.com", "graph.microsoft.com"}
SUPPORTED_WORKSPACE_TYPES = {"workspace", "workspacev2"}
SKIPPED_ERROR_CODES = {
    "EntityNotFound",
    "WorkspaceNotFound",
    "WorkspaceTypeNotSupported",
}


class PermissionAuditError(RuntimeError):
    def __init__(self, message, status_code=None, error_code=""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


@dataclass(frozen=True)
class ResolvedPrincipal:
    id: str
    display_name: str
    principal_type: str
    user_principal_name: str = ""


def _response_error(response):
    try:
        payload = response.json()
        error = payload.get("error") or payload
        code = error.get("errorCode") or error.get("code") or ""
        detail = error.get("message")
    except (AttributeError, ValueError):
        code = ""
        detail = None
    message = detail or getattr(response, "text", "")[:200] or "Unknown API error"
    return code, message


def _next_url(current_url, candidate):
    if not candidate:
        return None
    next_url = urljoin(current_url, candidate)
    if urlparse(next_url).hostname not in ALLOWED_API_HOSTS:
        raise PermissionAuditError("The API returned an unsupported pagination URL.")
    return next_url


def _fetch_pages(request_get, url, headers, params=None):
    values = []
    next_url = url
    next_params = params
    while next_url:
        response = request_get(
            next_url,
            headers=headers,
            params=next_params,
            timeout=30,
        )
        if response.status_code != 200:
            error_code, message = _response_error(response)
            raise PermissionAuditError(
                f"{response.status_code}: {message}",
                status_code=response.status_code,
                error_code=error_code,
            )
        payload = response.json()
        values.extend(payload.get("value", []))
        next_url = _next_url(next_url, payload.get("continuationUri") or payload.get("@odata.nextLink"))
        next_params = None
    return values


def _workspace_is_supported(workspace):
    state = str(workspace.get("state", "")).lower()
    if state in {"deleted", "removing", "removed"}:
        return False
    workspace_type = str(workspace.get("type", "")).lower()
    return not workspace_type or workspace_type in SUPPORTED_WORKSPACE_TYPES


def _warning_category(error):
    if error.error_code in SKIPPED_ERROR_CODES:
        return None
    if error.status_code in (401, 403):
        return "restricted"
    return "api"


def resolve_principal(query, graph_headers, request_get):
    query = str(query or "").strip()
    if not query:
        raise PermissionAuditError("Enter a user or group name, email, or object ID.")

    select = "id,displayName,userPrincipalName"
    user_response = request_get(
        f"{GRAPH_API_ROOT}/users/{quote(query, safe='')}",
        headers=graph_headers,
        params={"$select": select},
        timeout=30,
    )
    if user_response.status_code == 200:
        user = user_response.json()
        return ResolvedPrincipal(
            id=user["id"],
            display_name=user.get("displayName") or query,
            principal_type="User",
            user_principal_name=user.get("userPrincipalName", ""),
        )

    group_response = request_get(
        f"{GRAPH_API_ROOT}/groups/{quote(query, safe='')}",
        headers=graph_headers,
        params={"$select": "id,displayName,mail"},
        timeout=30,
    )
    if group_response.status_code == 200:
        group = group_response.json()
        return ResolvedPrincipal(
            id=group["id"],
            display_name=group.get("displayName") or query,
            principal_type="Group",
            user_principal_name=group.get("mail", ""),
        )

    escaped = query.replace("'", "''")
    groups = _fetch_pages(
        request_get,
        f"{GRAPH_API_ROOT}/groups",
        graph_headers,
        params={
            "$filter": f"mail eq '{escaped}' or displayName eq '{escaped}'",
            "$select": "id,displayName,mail",
            "$top": "2",
        },
    )
    if not groups:
        raise PermissionAuditError(f"No user or group matched '{query}'.")
    if len(groups) > 1:
        raise PermissionAuditError(
            f"More than one group matched '{query}'. Search by email or object ID."
        )
    group = groups[0]
    return ResolvedPrincipal(
        id=group["id"],
        display_name=group.get("displayName") or query,
        principal_type="Group",
        user_principal_name=group.get("mail", ""),
    )


def fetch_effective_principals(principal, graph_headers, request_get):
    collection = "users" if principal.principal_type == "User" else "groups"
    groups = _fetch_pages(
        request_get,
        f"{GRAPH_API_ROOT}/{collection}/{principal.id}/transitiveMemberOf/microsoft.graph.group",
        graph_headers,
        params={"$select": "id,displayName", "$top": "999"},
    )
    effective = {
        principal.id.lower(): {
            "id": principal.id,
            "displayName": principal.display_name,
            "type": principal.principal_type,
            "direct": True,
        }
    }
    for group in groups:
        effective[group["id"].lower()] = {
            "id": group["id"],
            "displayName": group.get("displayName") or group["id"],
            "type": "Group",
            "direct": False,
        }
    return effective


def _matching_workspace_assignments(assignments, effective_principals):
    matches = []
    for assignment in assignments:
        assigned = assignment.get("principal") or {}
        source = effective_principals.get(str(assigned.get("id", "")).lower())
        if source:
            matches.append(
                {
                    "role": assignment.get("role", "Unknown"),
                    "sourceId": source["id"],
                    "sourceName": source["displayName"],
                    "sourceType": source["type"],
                    "direct": source["direct"],
                }
            )
    return matches


def _role_scope(role):
    actions = []
    paths = []
    for rule in role.get("decisionRules", []):
        if str(rule.get("effect", "Permit")).lower() != "permit":
            continue
        for permission in rule.get("permission", []):
            values = permission.get("attributeValueIncludedIn", [])
            if permission.get("attributeName") == "Action":
                actions.extend(values)
            elif permission.get("attributeName") == "Path":
                paths.extend(values)
    return sorted(set(actions)) or ["Read"], sorted(set(paths)) or ["Entire item"]


def _matching_onelake_roles(
    roles,
    effective_principals,
    workspace_access,
    workspace_id,
    item_id,
):
    matches = []
    expected_source_path = f"{workspace_id}/{item_id}".lower()
    for role in roles:
        members = role.get("members") or {}
        sources = []
        for member in members.get("microsoftEntraMembers", []) or []:
            source = effective_principals.get(str(member.get("objectId", "")).lower())
            if source:
                sources.append(source)
        inherited_from_item = any(
            str(member.get("sourcePath", "")).lower() == expected_source_path
            for member in members.get("fabricItemMembers", []) or []
        )
        if workspace_access and inherited_from_item:
            sources.extend(
                {
                    "id": access["sourceId"],
                    "displayName": access["sourceName"],
                    "type": access["sourceType"],
                    "direct": access["direct"],
                }
                for access in workspace_access
            )
        if not sources:
            continue
        actions, paths = _role_scope(role)
        for source in sources:
            matches.append(
                {
                    "role": role.get("name", "Unnamed role"),
                    "actions": actions,
                    "paths": paths,
                    "sourceId": source["id"],
                    "sourceName": source["displayName"],
                    "sourceType": source["type"],
                    "direct": source["direct"],
                }
            )
    return matches


def audit_principal_access(
    principal,
    effective_principals,
    workspaces,
    fabric_headers,
    request_get,
):
    results = []
    warning_counts = {"restricted": 0, "api": 0}
    for workspace in workspaces:
        if not _workspace_is_supported(workspace):
            continue
        workspace_id = workspace.get("id")
        workspace_name = workspace.get("displayName") or workspace.get("name") or workspace_id
        workspace_warnings = set()
        try:
            assignments = _fetch_pages(
                request_get,
                f"{FABRIC_API_ROOT}/workspaces/{workspace_id}/roleAssignments",
                fabric_headers,
            )
            workspace_access = _matching_workspace_assignments(
                assignments, effective_principals
            )
        except PermissionAuditError as error:
            workspace_access = []
            category = _warning_category(error)
            if category is None:
                continue
            workspace_warnings.add(category)

        try:
            items = _fetch_pages(
                request_get,
                f"{FABRIC_API_ROOT}/workspaces/{workspace_id}/items",
                fabric_headers,
                params={"type": "Lakehouse"},
            )
        except PermissionAuditError as error:
            items = []
            category = _warning_category(error)
            if category is None:
                items = []
            else:
                workspace_warnings.add(category)

        lakehouses = []
        for item in items:
            if str(item.get("type", "")).lower() != "lakehouse":
                continue
            roles = None
            try:
                roles = _fetch_pages(
                    request_get,
                    f"{FABRIC_API_ROOT}/workspaces/{workspace_id}/items/{item['id']}/dataAccessRoles",
                    fabric_headers,
                )
                role_matches = _matching_onelake_roles(
                    roles,
                    effective_principals,
                    workspace_access,
                    workspace_id,
                    item["id"],
                )
            except PermissionAuditError as error:
                role_matches = []
                category = _warning_category(error)
                if category:
                    workspace_warnings.add(category)
            workspace_default_access = bool(workspace_access) and roles == []
            if workspace_default_access or role_matches:
                lakehouses.append(
                    {
                        "id": item["id"],
                        "name": item.get("displayName") or item["id"],
                        "roles": role_matches,
                        "workspaceInherited": workspace_default_access,
                    }
                )

        if workspace_access or lakehouses:
            results.append(
                {
                    "id": workspace_id,
                    "name": workspace_name,
                    "roles": workspace_access,
                    "lakehouses": lakehouses,
                }
            )
        for category in workspace_warnings:
            warning_counts[category] += 1

    warnings = []
    if warning_counts["restricted"]:
        warnings.append(
            f"{warning_counts['restricted']} workspace(s) could not be fully inspected "
            "because the signed-in administrator lacks access or a tenant/network "
            "policy blocked the request."
        )
    if warning_counts["api"]:
        warnings.append(
            f"{warning_counts['api']} workspace(s) returned an unexpected Fabric API "
            "error and may have incomplete results."
        )

    return {
        "principal": {
            "id": principal.id,
            "displayName": principal.display_name,
            "type": principal.principal_type,
            "userPrincipalName": principal.user_principal_name,
        },
        "effectivePrincipalCount": len(effective_principals),
        "workspaces": results,
        "workspaceCount": len(results),
        "lakehouseCount": sum(len(item["lakehouses"]) for item in results),
        "warnings": warnings,
    }