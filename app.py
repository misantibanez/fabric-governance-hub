import os
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
import requests
from azure.identity import DeviceCodeCredential

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

_credential = DeviceCodeCredential(tenant_id=os.environ["FABRIC_TENANT_ID"])

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

DEFAULT_SETTINGS = {
    "environments": ["Dev", "Int", "Prd"],
    "use_cases": ["Data Hub", "Use Case A", "Use Case B"],
    "branches": ["feature", "main"],
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def get_token():
    return _credential.get_token("https://api.fabric.microsoft.com/.default").token


def get_graph_token():
    return _credential.get_token("https://graph.microsoft.com/.default").token


def get_powerbi_token():
    return _credential.get_token("https://analysis.windows.net/powerbi/api/.default").token


def get_headers():
    return {"Authorization": f"Bearer {get_token()}"}


def get_powerbi_headers():
    return {"Authorization": f"Bearer {get_powerbi_token()}"}


def resolve_principal(email):
    """Resolve an email/UPN to a principal ID and type (User or Group) via Graph."""
    graph_headers = {"Authorization": f"Bearer {get_graph_token()}"}
    # Try user first
    resp = requests.get(
        f"https://graph.microsoft.com/v1.0/users/{email}",
        headers=graph_headers,
    )
    if resp.status_code == 200:
        return resp.json()["id"], "User"
    # Try group by displayName
    resp = requests.get(
        "https://graph.microsoft.com/v1.0/groups",
        headers=graph_headers,
        params={"$filter": f"mail eq '{email}' or displayName eq '{email}'"},
    )
    if resp.status_code == 200 and resp.json().get("value"):
        return resp.json()["value"][0]["id"], "Group"
    return None, None


# --- Power BI admin APIs (use PBI token) ---

def fetch_capacities_admin(pbi_headers):
    resp = requests.get(
        "https://api.powerbi.com/v1.0/myorg/admin/capacities", headers=pbi_headers
    )
    if resp.status_code in (401, 403):
        print(f"[WARN] fetch_capacities_admin failed: {resp.status_code} - {resp.text}")
        return None
    resp.raise_for_status()
    return resp.json().get("value", [])


def fetch_workspaces_admin(pbi_headers):
    url = "https://api.powerbi.com/v1.0/myorg/admin/groups?$top=5000"
    workspaces = []
    while url:
        resp = requests.get(url, headers=pbi_headers)
        if resp.status_code in (401, 403):
            print(f"[WARN] fetch_workspaces_admin failed: {resp.status_code} - {resp.text}")
            return None
        resp.raise_for_status()
        data = resp.json()
        workspaces.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return workspaces


# --- Fabric APIs (use Fabric token) ---

def fetch_capacities(fabric_headers):
    url = "https://api.fabric.microsoft.com/v1/capacities"
    capacities = []
    while url:
        resp = requests.get(url, headers=fabric_headers)
        resp.raise_for_status()
        data = resp.json()
        capacities.extend(data.get("value", []))
        url = data.get("continuationUri")
    return capacities


def fetch_workspaces(fabric_headers):
    url = "https://api.fabric.microsoft.com/v1/workspaces"
    workspaces = []
    while url:
        resp = requests.get(url, headers=fabric_headers)
        resp.raise_for_status()
        data = resp.json()
        workspaces.extend(data.get("value", []))
        url = data.get("continuationUri")
    return workspaces


# --- Fabric admin APIs (use Fabric token) ---

def fetch_domains(fabric_headers):
    resp = requests.get(
        "https://api.fabric.microsoft.com/v1/admin/domains", headers=fabric_headers
    )
    if resp.status_code in (401, 403):
        print(f"[WARN] fetch_domains failed: {resp.status_code} - {resp.text}")
        return []
    resp.raise_for_status()
    return resp.json().get("domains", [])


def fetch_tags(fabric_headers):
    resp = requests.get(
        "https://api.fabric.microsoft.com/v1/admin/tags", headers=fabric_headers
    )
    if resp.status_code in (401, 403):
        print(f"[WARN] fetch_tags failed: {resp.status_code} - {resp.text}")
        return []
    resp.raise_for_status()
    return resp.json().get("value", [])


# --- Fabric public APIs (use Fabric token) ---


def fetch_gateways(headers):
    url = "https://api.fabric.microsoft.com/v1/gateways"
    gateways = []
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        gateways.extend(data.get("value", []))
        url = data.get("continuationUri")
    return gateways


def fetch_gateway_datasources(pbi_headers, gateway_id):
    resp = requests.get(
        f"https://api.powerbi.com/v1.0/myorg/admin/gateways/{gateway_id}/datasources",
        headers=pbi_headers,
    )
    if resp.status_code == 200:
        return resp.json().get("value", [])
    return []


def fetch_connections(headers):
    url = "https://api.fabric.microsoft.com/v1/connections"
    connections = []
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        connections.extend(data.get("value", []))
        url = data.get("continuationUri")
    return connections


@app.route("/")
def menu():
    return render_template("menu.html")


@app.route("/create-workspace-form")
def create_workspace_form():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()

    # Intenta PBI admin APIs primero, si falla usa Fabric APIs
    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)
    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)

    # Fabric admin APIs
    domains_raw = fetch_domains(fabric_headers)
    tags = fetch_tags(fabric_headers)

    # Fabric public APIs
    gateways = fetch_gateways(fabric_headers)
    connections = fetch_connections(fabric_headers)

    # Power BI admin API
    for gw in gateways:
        gw["datasources"] = fetch_gateway_datasources(pbi_headers, gw["id"])

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    for d in domains_raw:
        parent_id = d.get("parentDomainId")
        d["parentName"] = domain_map.get(parent_id, "") if parent_id else ""

    domains = [d for d in domains_raw if not d.get("parentDomainId")]
    subdomains = [d for d in domains_raw if d.get("parentDomainId")]

    # Filter GitHub source control connections
    git_connections = []
    for c in connections:
        conn_type = c.get("connectionDetails", {}).get("type", "")
        if "github" in conn_type.lower():
            git_connections.append(c)
    if not git_connections:
        print(f"[DEBUG] Connection types: {[c.get('connectionDetails', {}).get('type', '') for c in connections[:10]]}")

    return render_template(
        "index.html",
        capacities=capacities,
        workspaces=workspaces,
        domains=domains,
        subdomains=subdomains,
        tags=tags,
        gateways=gateways,
        connections=connections,
        git_connections=git_connections,
        settings=load_settings(),
    )


@app.route("/create-tag", methods=["POST"])
def create_tag():
    from flask import jsonify
    fabric_headers = get_headers()
    data = request.get_json()
    tag_name = data.get("displayName", "").strip()
    if not tag_name:
        return jsonify({"error": "Tag name is required."}), 400

    resp = requests.post(
        "https://api.fabric.microsoft.com/v1/admin/tags/bulkCreateTags",
        headers={**fabric_headers, "Content-Type": "application/json"},
        json={"createTagsRequest": [{"displayName": tag_name}]},
    )
    if resp.status_code == 201:
        tags = resp.json().get("tags", [])
        return jsonify({"tag": tags[0] if tags else {}}), 201
    return jsonify({"error": f"{resp.status_code} - {resp.text[:200]}"}), resp.status_code


@app.route("/create-workspace", methods=["POST"])
def create_workspace():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()
    name = request.form["name"].strip()
    description = request.form.get("description", "").strip()
    capacity_id = request.form["capacity_id"]
    domain_id = request.form.get("domain_id", "")

    # 1. Create workspace (Fabric API)
    body = {"displayName": name}
    if description:
        body["description"] = description
    resp = requests.post(
        "https://api.fabric.microsoft.com/v1/workspaces",
        headers={**fabric_headers, "Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code not in (200, 201):
        flash(f"Error creating workspace: {resp.status_code} - {resp.text}", "error")
        return redirect(url_for("create_workspace_form"))

    workspace_id = resp.json()["id"]

    # 2. Assign to capacity (Fabric API)
    resp2 = requests.post(
        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/assignToCapacity",
        headers={**fabric_headers, "Content-Type": "application/json"},
        json={"capacityId": capacity_id},
    )
    if resp2.status_code not in (200, 202):
        flash(
            f"Workspace created but failed to assign capacity: {resp2.status_code} - {resp2.text}",
            "error",
        )
        return redirect(url_for("create_workspace_form"))

    # 3. Assign to domain (Fabric admin API)
    if domain_id:
        resp3 = requests.post(
            f"https://api.fabric.microsoft.com/v1/admin/domains/{domain_id}/assignWorkspaces",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"workspacesIds": [workspace_id]},
        )
        if resp3.status_code not in (200, 201, 204):
            flash(
                f"Workspace created and assigned to capacity, but failed to assign domain: {resp3.status_code} - {resp3.text}",
                "error",
            )
            return redirect(url_for("create_workspace_form"))

    # 4. Apply tags (Fabric API)
    tag_ids = request.form.getlist("tags")
    tag_errors = []
    if tag_ids:
        resp_tags = requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/applyTags",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"tags": tag_ids},
        )
        if resp_tags.status_code != 200:
            tag_errors.append(
                f"Failed to apply tags: {resp_tags.status_code} - {resp_tags.text}"
            )

    # 5. Configure Log Analytics (Power BI admin API)
    la_subscription = request.form.get("la_subscription_id", "").strip()
    la_resource_group = request.form.get("la_resource_group", "").strip()
    la_workspace_name = request.form.get("la_workspace_name", "").strip()
    la_errors = []
    if la_subscription and la_resource_group and la_workspace_name:
        resp_la = requests.patch(
            f"https://api.powerbi.com/v1.0/myorg/admin/groups/{workspace_id}",
            headers={**pbi_headers, "Content-Type": "application/json"},
            json={
                "logAnalyticsWorkspace": {
                    "subscriptionId": la_subscription,
                    "resourceGroup": la_resource_group,
                    "resourceName": la_workspace_name,
                }
            },
        )
        if resp_la.status_code != 200:
            la_errors.append(
                f"Failed to configure Log Analytics: {resp_la.status_code} - {resp_la.text}"
            )

    # 6. Assign role groups (Fabric API)
    roles = {
        "Admin": request.form.get("admins", "").strip(),
        "Contributor": request.form.get("contributors", "").strip(),
        "Viewer": request.form.get("viewers", "").strip(),
    }
    role_errors = []
    for role, group_name in roles.items():
        if not group_name:
            continue
        principal_id, principal_type = resolve_principal(group_name)
        if not principal_id:
            role_errors.append(f"{group_name} as {role}: not found in directory")
            continue
        resp_role = requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/roleAssignments",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={
                "principal": {"id": principal_id, "type": principal_type},
                "role": role,
            },
        )
        if resp_role.status_code not in (200, 201):
            role_errors.append(f"{group_name} as {role}: {resp_role.status_code} - {resp_role.text}")

    # 7. Create initial workspace items
    item_errors = []
    api_items = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    api_folders = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/folders"
    item_headers = {**fabric_headers, "Content-Type": "application/json"}

    # 7a. Create root folder path if specified (supports nested paths like "Project/Test")
    root_folder_name = request.form.get("root_folder_name", "").strip().strip("/")
    root_folder_id = None
    if root_folder_name:
        parent_id = None
        for folder_part in root_folder_name.split("/"):
            folder_part = folder_part.strip()
            if not folder_part:
                continue
            folder_body = {"displayName": folder_part}
            if parent_id:
                folder_body["parentFolderId"] = parent_id
            resp_rf = requests.post(api_folders, headers=item_headers, json=folder_body)
            if resp_rf.status_code in (200, 201):
                parent_id = resp_rf.json().get("id")
            else:
                item_errors.append(f"Folder '{folder_part}': {resp_rf.status_code} - {resp_rf.text[:150]}")
                break
        root_folder_id = parent_id

    # 7b. Create folder "Notebook" (inside root if exists)
    folder_body = {"displayName": "Notebook"}
    if root_folder_id:
        folder_body["parentFolderId"] = root_folder_id
    resp_nf = requests.post(api_folders, headers=item_headers, json=folder_body)
    if resp_nf.status_code in (200, 201):
        notebook_folder_id = resp_nf.json().get("id")
        # Create notebook inside folder
        resp_nb = requests.post(api_items, headers=item_headers, json={"displayName": "nb_00_init", "type": "Notebook", "folderId": notebook_folder_id})
        if resp_nb.status_code not in (200, 201, 202):
            item_errors.append(f"nb_00_init: {resp_nb.status_code} - {resp_nb.text[:150]}")
    else:
        item_errors.append(f"Folder Notebook: {resp_nf.status_code} - {resp_nf.text[:150]}")

    # 7c. Create folder "Pipeline" (inside root if exists)
    folder_body = {"displayName": "Pipeline"}
    if root_folder_id:
        folder_body["parentFolderId"] = root_folder_id
    resp_pf = requests.post(api_folders, headers=item_headers, json=folder_body)
    if resp_pf.status_code in (200, 201):
        pipeline_folder_id = resp_pf.json().get("id")
        # Create pipeline inside folder
        resp_pl = requests.post(api_items, headers=item_headers, json={"displayName": "p_00_init", "type": "DataPipeline", "folderId": pipeline_folder_id})
        if resp_pl.status_code not in (200, 201, 202):
            item_errors.append(f"p_00_init: {resp_pl.status_code} - {resp_pl.text[:150]}")
    else:
        item_errors.append(f"Folder Pipeline: {resp_pf.status_code} - {resp_pf.text[:150]}")

    # 7e. Create lakehouse (same level as Notebook/Pipeline folders)
    lakehouse_name = request.form.get("lakehouse_name", "").strip()
    if lakehouse_name:
        lh_body = {"displayName": lakehouse_name, "type": "Lakehouse"}
        if root_folder_id:
            lh_body["folderId"] = root_folder_id
        resp_lh = requests.post(api_items, headers=item_headers, json=lh_body)
        if resp_lh.status_code not in (200, 201, 202):
            item_errors.append(f"Lakehouse {lakehouse_name}: {resp_lh.status_code} - {resp_lh.text[:150]}")

    # 8. Connect to GitHub (optional)
    git_repo_url = request.form.get("git_repo_url", "").strip().rstrip("/")
    git_branch = request.form.get("git_branch", "").strip()
    git_folder = request.form.get("git_folder", "").strip()
    git_connection_id = request.form.get("git_connection_id", "").strip()
    git_errors = []
    if git_repo_url and git_branch and git_connection_id:
        # Parse owner and repo from URL: https://github.com/{owner}/{repo}
        parts = git_repo_url.replace("https://github.com/", "").split("/")
        git_owner = parts[0] if len(parts) >= 1 else ""
        git_repo = parts[1] if len(parts) >= 2 else ""
        if git_owner and git_repo:
            resp_git = requests.post(
                f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/connect",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={
                    "gitProviderDetails": {
                        "gitProviderType": "GitHub",
                        "ownerName": git_owner,
                        "repositoryName": git_repo,
                        "branchName": git_branch,
                        "directoryName": git_folder or "/",
                    },
                    "myGitCredentials": {
                        "source": "ConfiguredConnection",
                        "connectionId": git_connection_id,
                    },
                },
            )
            if resp_git.status_code != 200:
                git_errors.append(f"Git connect: {resp_git.status_code} - {resp_git.text[:200]}")
        else:
            git_errors.append("Could not parse owner/repo from URL")

    all_errors = tag_errors + la_errors + role_errors + item_errors + git_errors
    if all_errors:
        flash(
            f"Workspace created but some assignments failed: {'; '.join(all_errors)}",
            "error",
        )
    else:
        flash(f"Workspace '{name}' created successfully!", "success")
    return redirect(url_for("create_workspace_form"))


@app.route("/workspace-map")
def workspace_map():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()

    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)
    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)
    domains_raw = fetch_domains(fabric_headers)
    tags = fetch_tags(fabric_headers)

    # Enrich workspaces with tags and domainId
    enriched = []
    for ws in workspaces:
        resp = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws['id']}",
            headers=fabric_headers,
        )
        if resp.status_code == 200:
            detail = resp.json()
            ws["tags"] = detail.get("tags", [])
            ws["domainId"] = detail.get("domainId")
            enriched.append(ws)
        elif resp.status_code != 404:
            enriched.append(ws)
    workspaces = enriched

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    capacity_map = {c["id"]: c.get("displayName") or c.get("name", "") for c in capacities}

    for d in domains_raw:
        parent_id = d.get("parentDomainId")
        d["parentName"] = domain_map.get(parent_id, "") if parent_id else ""

    domains = [d for d in domains_raw if not d.get("parentDomainId")]
    subdomains = [d for d in domains_raw if d.get("parentDomainId")]

    return render_template(
        "workspace_map.html",
        workspaces=workspaces,
        capacities=capacities,
        domains=domains,
        subdomains=subdomains,
        tags=tags,
        workspaces_json=json.dumps(workspaces),
        domain_map_json=json.dumps(domain_map),
        capacity_map_json=json.dumps(capacity_map),
        settings=load_settings(),
    )


@app.route("/modify-workspaces")
def modify_workspaces():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()

    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)
    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)
    domains_raw = fetch_domains(fabric_headers)
    tags = fetch_tags(fabric_headers)

    # Enrich each workspace with tags and domainId; filter out deleted ones
    deleted_ids = set(session.pop("deleted_workspace_ids", []))
    enriched = []
    for ws in workspaces:
        if ws["id"] in deleted_ids:
            continue
        resp = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws['id']}",
            headers=fabric_headers,
        )
        if resp.status_code == 200:
            detail = resp.json()
            ws["tags"] = detail.get("tags", [])
            ws["domainId"] = detail.get("domainId")
            enriched.append(ws)
        elif resp.status_code == 404:
            continue
        else:
            enriched.append(ws)
    workspaces = enriched

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    for d in domains_raw:
        parent_id = d.get("parentDomainId")
        d["parentName"] = domain_map.get(parent_id, "") if parent_id else ""

    domains = [d for d in domains_raw if not d.get("parentDomainId")]
    subdomains = [d for d in domains_raw if d.get("parentDomainId")]

    return render_template(
        "modify_workspaces.html",
        workspaces=workspaces,
        capacities=capacities,
        domains=domains,
        subdomains=subdomains,
        tags=tags,
        domain_map=domain_map,
    )


@app.route("/modify-workspaces/apply-tags", methods=["POST"])
def batch_apply_tags():
    fabric_headers = get_headers()
    workspace_ids = json.loads(request.form["workspace_ids"])
    tag_ids = request.form.getlist("tag_ids")
    if not tag_ids:
        flash("No tags selected.", "error")
        return redirect(url_for("modify_workspaces"))

    errors = []
    for ws_id in workspace_ids:
        resp = requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/applyTags",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"tags": tag_ids},
        )
        if resp.status_code != 200:
            errors.append(f"{ws_id}: {resp.status_code} - {resp.text[:200]}")

    if errors:
        flash(f"Tags applied with errors: {'; '.join(errors)}", "error")
    else:
        flash(f"Tags applied to {len(workspace_ids)} workspace(s).", "success")
    return redirect(url_for("modify_workspaces"))


@app.route("/modify-workspaces/unapply-tags", methods=["POST"])
def batch_unapply_tags():
    fabric_headers = get_headers()
    workspace_ids = json.loads(request.form["workspace_ids"])
    tag_ids = request.form.getlist("tag_ids")
    if not tag_ids:
        flash("No tags selected.", "error")
        return redirect(url_for("modify_workspaces"))

    errors = []
    for ws_id in workspace_ids:
        resp = requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/unapplyTags",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"tags": tag_ids},
        )
        if resp.status_code != 200:
            errors.append(f"{ws_id}: {resp.status_code}")

    if errors:
        flash(f"Tags removed with errors: {'; '.join(errors)}", "error")
    else:
        flash(f"Tags removed from {len(workspace_ids)} workspace(s).", "success")
    return redirect(url_for("modify_workspaces"))


@app.route("/modify-workspaces/assign-domain", methods=["POST"])
def batch_assign_domain():
    fabric_headers = get_headers()
    workspace_ids = json.loads(request.form["workspace_ids"])
    domain_id = request.form["domain_id"]

    resp = requests.post(
        f"https://api.fabric.microsoft.com/v1/admin/domains/{domain_id}/assignWorkspaces",
        headers={**fabric_headers, "Content-Type": "application/json"},
        json={"workspacesIds": workspace_ids},
    )
    if resp.status_code in (200, 201, 204):
        flash(f"Domain assigned to {len(workspace_ids)} workspace(s).", "success")
    else:
        flash(f"Failed to assign domain: {resp.status_code} - {resp.text}", "error")
    return redirect(url_for("modify_workspaces"))


@app.route("/modify-workspaces/assign-capacity", methods=["POST"])
def batch_assign_capacity():
    fabric_headers = get_headers()
    workspace_ids = json.loads(request.form["workspace_ids"])
    capacity_id = request.form["capacity_id"]

    errors = []
    for ws_id in workspace_ids:
        resp = requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/assignToCapacity",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"capacityId": capacity_id},
        )
        if resp.status_code not in (200, 202):
            errors.append(f"{ws_id}: {resp.status_code}")

    if errors:
        flash(f"Capacity assigned with errors: {'; '.join(errors)}", "error")
    else:
        flash(f"Capacity assigned to {len(workspace_ids)} workspace(s).", "success")
    return redirect(url_for("modify_workspaces"))


@app.route("/modify-workspaces/delete", methods=["POST"])
def batch_delete_workspaces():
    fabric_headers = get_headers()
    workspace_ids = json.loads(request.form["workspace_ids"])

    errors = []
    for ws_id in workspace_ids:
        resp = requests.delete(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}",
            headers=fabric_headers,
        )
        if resp.status_code in (200, 204, 404):
            continue
        errors.append(f"{ws_id}: {resp.status_code}")

    deleted = [ws_id for ws_id in workspace_ids if ws_id not in [e.split(":")[0] for e in errors]]
    session["deleted_workspace_ids"] = deleted

    if errors:
        flash(f"Deleted with errors: {'; '.join(errors)}", "error")
    else:
        flash(f"Deleted {len(workspace_ids)} workspace(s).", "success")
    return redirect(url_for("modify_workspaces"))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        settings = {
            "environments": [x.strip() for x in request.form.get("environments", "").split(",") if x.strip()],
            "use_cases": [x.strip() for x in request.form.get("use_cases", "").split(",") if x.strip()],
            "branches": [x.strip() for x in request.form.get("branches", "").split(",") if x.strip()],
        }
        save_settings(settings)
        flash("Settings saved.", "success")
        return redirect(url_for("settings_page"))

    return render_template("settings.html", settings=load_settings())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
