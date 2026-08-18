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
    "branches": ["feature", "main"],
    "mpe_cognitive_services_resource_id": "",
    "mpe_keyvault_resource_id": "",
    "compliance_domain_required_tag": "DHUB",
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


def fetch_domain_tags(fabric_headers, domain_id):
    """Filter admin tags scoped to a domain. For subdomains, inherit parent's tags."""
    all_tags = fetch_tags(fabric_headers)
    domain_tags = [
        t for t in all_tags
        if domain_id in json.dumps(t.get("scope", {}))
    ]
    # If subdomain has no tags, look up parent domain and inherit its tags
    if not domain_tags:
        domains = fetch_domains(fabric_headers)
        domain_obj = next((d for d in domains if d["id"] == domain_id), None)
        parent_id = domain_obj.get("parentDomainId") if domain_obj else None
        if parent_id:
            domain_tags = [
                t for t in all_tags
                if parent_id in json.dumps(t.get("scope", {}))
            ]
    return domain_tags


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


def fetch_gateways_pbi(pbi_headers):
    resp = requests.get(
        "https://api.powerbi.com/v2.0/myorg/gatewayclusters", headers=pbi_headers
    )
    if resp.status_code in (401, 403):
        return []
    if resp.status_code != 200:
        return []
    gateways = resp.json().get("value", [])
    for gw in gateways:
        members = gw.get("memberGateways", []) or []
        contact_info = ""
        for m in members:
            annotation_str = m.get("annotation", "")
            if annotation_str and not contact_info:
                try:
                    ann = json.loads(annotation_str)
                    contacts = ann.get("gatewayContactInformation", [])
                    contact_info = "; ".join(contacts) if isinstance(contacts, list) else str(contacts)
                except (json.JSONDecodeError, TypeError):
                    pass
        gw["contactInfo"] = contact_info
        perms = gw.get("permissions", []) or []
        user_names = []
        for p in perms:
            name = p.get("principalName", "") or p.get("displayName", "") or p.get("id", "")
            role = p.get("role", "")
            user_names.append(f"{name} ({role})" if role else name)
        gw["users"] = "; ".join(user_names)
    return gateways


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

    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)

    # Fabric admin APIs
    domains_raw = fetch_domains(fabric_headers)
    tags = fetch_tags(fabric_headers)

    # Fabric public APIs — only connections (for git)
    connections = fetch_connections(fabric_headers)

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    for d in domains_raw:
        parent_id = d.get("parentDomainId")
        d["parentName"] = domain_map.get(parent_id, "") if parent_id else ""

    domains = [d for d in domains_raw if not d.get("parentDomainId")]
    subdomains = [d for d in domains_raw if d.get("parentDomainId")]

    git_connections = [
        c for c in connections
        if "github" in c.get("connectionDetails", {}).get("type", "").lower()
    ]

    return render_template(
        "index.html",
        capacities=capacities,
        domains=domains,
        subdomains=subdomains,
        tags=tags,
        git_connections=git_connections,
        settings=load_settings(),
    )


@app.route("/tenant-overview")
def tenant_overview():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()

    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)
    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)
    domains_raw = fetch_domains(fabric_headers)
    tags = fetch_tags(fabric_headers)
    gateways = fetch_gateways(fabric_headers)
    connections = fetch_connections(fabric_headers)

    for gw in gateways:
        gw["datasources"] = fetch_gateway_datasources(pbi_headers, gw["id"])

    # Enrich gateways with contact info and users from PBI v2 API
    pbi_gateways = fetch_gateways_pbi(pbi_headers)
    pbi_gw_map = {g["id"]: g for g in pbi_gateways}
    for gw in gateways:
        pbi_gw = pbi_gw_map.get(gw["id"], {})
        gw["contactInfo"] = pbi_gw.get("contactInfo", "")
        gw["users"] = pbi_gw.get("users", "")

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    for d in domains_raw:
        parent_id = d.get("parentDomainId")
        d["parentName"] = domain_map.get(parent_id, "") if parent_id else ""

    domains = [d for d in domains_raw if not d.get("parentDomainId")]
    subdomains = [d for d in domains_raw if d.get("parentDomainId")]

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

    return render_template(
        "tenant_overview.html",
        capacities=capacities,
        workspaces=workspaces,
        domains=domains,
        subdomains=subdomains,
        tags=tags,
        gateways=gateways,
        connections=connections,
        domain_map=domain_map,
    )


@app.route("/domain-tags/<domain_id>")
def get_domain_tags(domain_id):
    from flask import jsonify
    fabric_headers = get_headers()
    tags = fetch_domain_tags(fabric_headers, domain_id)
    return jsonify(tags)


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

    # 2b. Provision workspace identity
    resp_id = requests.post(
        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/provisionIdentity",
        headers=fabric_headers,
    )
    if resp_id.status_code not in (200, 202):
        flash(
            f"Workspace created but failed to provision identity: {resp_id.status_code} - {resp_id.text}",
            "error",
        )

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

    # 8. Create managed private endpoints
    mpe_errors = []
    settings = load_settings()
    mpe_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/managedPrivateEndpoints"
    mpe_headers = {**fabric_headers, "Content-Type": "application/json"}
    kv_resource_id = settings.get("mpe_keyvault_resource_id", "")
    if kv_resource_id:
        resp_mpe = requests.post(mpe_url, headers=mpe_headers, json={
            "name": f"mpe-kv-{name}",
            "targetPrivateLinkResourceId": kv_resource_id,
            "targetSubresourceType": "vault",
            "requestMessage": f"Fabric {name}",
        })
        if resp_mpe.status_code != 201:
            mpe_errors.append(f"MPE Key Vault: {resp_mpe.status_code} - {resp_mpe.text[:200]}")
    cs_resource_id = settings.get("mpe_cognitive_services_resource_id", "")
    if cs_resource_id and request.form.get("mpe_cognitive_services"):
        resp_mpe = requests.post(mpe_url, headers=mpe_headers, json={
            "name": f"mpe-cs-{name}",
            "targetPrivateLinkResourceId": cs_resource_id,
            "targetSubresourceType": "account",
            "requestMessage": f"Fabric {name}",
        })
        if resp_mpe.status_code != 201:
            mpe_errors.append(f"MPE Cognitive Services: {resp_mpe.status_code} - {resp_mpe.text[:200]}")

    # 9. Connect to GitHub (optional)
    git_repo_url = request.form.get("git_repo_url", "").strip().rstrip("/")
    git_branch = request.form.get("git_branch", "").strip()
    git_folder = request.form.get("git_folder", "").strip().strip("/")
    git_connection_id = request.form.get("git_connection_id", "").strip()
    git_errors = []
    if git_repo_url and git_branch and git_connection_id:
        # Parse owner and repo from URL: https://github.com/{owner}/{repo}
        parts = git_repo_url.replace("https://github.com/", "").split("/")
        git_owner = parts[0] if len(parts) >= 1 else ""
        git_repo = parts[1] if len(parts) >= 2 else ""
        if git_owner and git_repo:
            # Create folder in GitHub repo if it doesn't exist
            if git_folder:
                github_pat = os.environ.get("GITHUB_PAT", "")
                print(f"[DEBUG] GITHUB_PAT loaded: {'yes' if github_pat else 'NO - not set in .env'}")
                if github_pat:
                    gitkeep_path = f"{git_folder}/.gitkeep"
                    gh_headers = {"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"}
                    gh_resp = requests.get(
                        f"https://api.github.com/repos/{git_owner}/{git_repo}/contents/{gitkeep_path}",
                        headers=gh_headers,
                        params={"ref": git_branch},
                    )
                    print(f"[DEBUG] GitHub check folder: {gh_resp.status_code}")
                    if gh_resp.status_code == 404:
                        import base64
                        gh_create = requests.put(
                            f"https://api.github.com/repos/{git_owner}/{git_repo}/contents/{gitkeep_path}",
                            headers=gh_headers,
                            json={
                                "message": f"Create folder {git_folder}",
                                "content": base64.b64encode(b"").decode(),
                                "branch": git_branch,
                            },
                        )
                        print(f"[DEBUG] GitHub create folder: {gh_create.status_code} - {gh_create.text[:300]}")
                        if gh_create.status_code not in (200, 201):
                            git_errors.append(f"GitHub create folder: {gh_create.status_code} - {gh_create.text[:200]}")

            # Connect workspace to git
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
                resp_init = requests.post(
                    f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/initializeConnection",
                    headers={**fabric_headers, "Content-Type": "application/json"},
                    json={"initializationStrategy": "PreferWorkspace"},
                )
                if resp_init.status_code not in (200, 202):
                    git_errors.append(f"Git initialize: {resp_init.status_code} - {resp_init.text[:200]}")
        else:
            git_errors.append("Could not parse owner/repo from URL")

    all_errors = tag_errors + la_errors + role_errors + item_errors + mpe_errors + git_errors
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


@app.route("/developer-workspaces")
def developer_workspaces():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()
    settings = load_settings()

    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)
    capacities = fetch_capacities_admin(pbi_headers) or fetch_capacities(fabric_headers)
    domains_raw = fetch_domains(fabric_headers)

    domain_map = {d["id"]: d["displayName"] for d in domains_raw}
    capacity_map = {c["id"]: c.get("displayName") or c.get("name", "") for c in capacities}

    # Enrich workspaces and filter to those with "Main" tag
    main_workspaces = []
    for ws in workspaces:
        if ws.get("type") and ws["type"] != "Workspace":
            continue
        resp = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws['id']}",
            headers=fabric_headers,
        )
        if resp.status_code != 200:
            continue
        detail = resp.json()
        ws["tags"] = detail.get("tags", [])
        ws["domainId"] = detail.get("domainId")
        ws["capacityId"] = detail.get("capacityId", ws.get("capacityId"))
        tag_names = [t.get("displayName", "").lower() for t in ws["tags"]]
        if "main" not in tag_names:
            continue
        # Get git connection info
        resp_git = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws['id']}/git/connection",
            headers=fabric_headers,
        )
        if resp_git.status_code == 200:
            git_details = resp_git.json().get("gitProviderDetails", {})
            ws["git_owner"] = git_details.get("ownerName", "")
            ws["git_repo"] = git_details.get("repositoryName", "")
            ws["git_folder"] = git_details.get("directoryName", "")
        main_workspaces.append(ws)

    return render_template(
        "developer_workspaces.html",
        main_workspaces=main_workspaces,
        capacity_map_json=json.dumps(capacity_map),
        domain_map_json=json.dumps(domain_map),
    )


@app.route("/create-developer-workspaces", methods=["POST"])
def create_developer_workspaces():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()
    settings = load_settings()
    main_ws_id = request.form["main_workspace_id"]
    dev_count = int(request.form.get("dev_count", 0))

    # Get main workspace details
    resp = requests.get(
        f"https://api.fabric.microsoft.com/v1/workspaces/{main_ws_id}",
        headers=fabric_headers,
    )
    if resp.status_code != 200:
        flash("Could not load main workspace details.", "error")
        return redirect(url_for("developer_workspaces"))
    main_ws = resp.json()
    main_name = main_ws.get("displayName", "")
    main_tags = main_ws.get("tags", [])
    capacity_id = main_ws.get("capacityId", "")
    domain_id = main_ws.get("domainId", "")

    # Get main workspace git info
    resp_git = requests.get(
        f"https://api.fabric.microsoft.com/v1/workspaces/{main_ws_id}/git/connection",
        headers=fabric_headers,
    )
    git_owner, git_repo, git_folder, main_conn_id = "", "", "", ""
    if resp_git.status_code == 200:
        git_conn = resp_git.json()
        gd = git_conn.get("gitProviderDetails", {})
        git_owner = gd.get("ownerName", "")
        git_repo = gd.get("repositoryName", "")
        git_folder = gd.get("directoryName", "")
        creds = git_conn.get("myGitCredentials", {})
        main_conn_id = creds.get("connectionId", "")

    # Get main workspace roles
    resp_roles = requests.get(
        f"https://api.fabric.microsoft.com/v1/workspaces/{main_ws_id}/roleAssignments",
        headers=fabric_headers,
    )
    role_assignments = resp_roles.json().get("value", []) if resp_roles.status_code == 200 else []

    # Swap Main tag for feature
    feature_tag_ids = []
    for t in main_tags:
        name = t.get("displayName", "")
        if name.lower() == "main":
            # Find the "feature" tag
            all_tags = fetch_tags(fabric_headers)
            for at in all_tags:
                if at.get("displayName", "").lower() == "feature":
                    feature_tag_ids.append(at["id"])
                    break
        else:
            feature_tag_ids.append(t["id"])

    github_pat = os.environ.get("GITHUB_PAT", "")
    all_results = []

    for i in range(1, dev_count + 1):
        alias = request.form.get(f"dev_alias_{i}", "").strip()
        gh_user = request.form.get(f"dev_github_user_{i}", "").strip()
        gh_pat = request.form.get(f"dev_github_pat_{i}", "").strip()
        if not alias or not gh_user or not gh_pat:
            continue

        dev_errors = []
        branch_name = f"feature/{alias}"
        ws_name = main_name.replace("main", alias).replace("Main", alias) if "main" in main_name.lower() else f"{main_name}-{alias}"

        # 1. Create GitHub branch feature/{alias} from main
        if git_owner and git_repo and github_pat:
            # Get main branch SHA
            resp_ref = requests.get(
                f"https://api.github.com/repos/{git_owner}/{git_repo}/git/refs/heads/main",
                headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"},
            )
            if resp_ref.status_code == 200:
                main_sha = resp_ref.json()["object"]["sha"]
                # Check if branch exists
                resp_br = requests.get(
                    f"https://api.github.com/repos/{git_owner}/{git_repo}/git/refs/heads/{branch_name}",
                    headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"},
                )
                if resp_br.status_code == 404:
                    resp_create_br = requests.post(
                        f"https://api.github.com/repos/{git_owner}/{git_repo}/git/refs",
                        headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"},
                        json={"ref": f"refs/heads/{branch_name}", "sha": main_sha},
                    )
                    if resp_create_br.status_code not in (200, 201):
                        dev_errors.append(f"GitHub branch: {resp_create_br.status_code} - {resp_create_br.text[:150]}")
            else:
                dev_errors.append(f"GitHub get main SHA: {resp_ref.status_code}")

        # 2. Create Fabric GitHub connection for developer
        conn_name = f"cx-gh-{alias}"
        dev_conn_id = None
        # Check if connection already exists
        connections = fetch_connections(fabric_headers)
        for c in connections:
            if c.get("displayName", "") == conn_name:
                dev_conn_id = c["id"]
                break
        if not dev_conn_id:
            conn_body = {
                "connectivityType": "ShareableCloud",
                "displayName": conn_name,
                "connectionDetails": {
                    "type": "GitHubSourceControl",
                    "creationMethod": "GitHubSourceControl.Contents",
                    "parameters": [{"dataType": "Text", "name": "url", "value": f"https://github.com/{git_owner}/{git_repo}"}],
                },
                "credentialDetails": {
                    "credentials": {"credentialType": "Key", "key": gh_pat},
                },
            }
            resp_conn = requests.post(
                "https://api.fabric.microsoft.com/v1/connections",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json=conn_body,
            )
            if resp_conn.status_code == 201:
                dev_conn_id = resp_conn.json()["id"]
            else:
                dev_errors.append(f"Fabric connection: {resp_conn.status_code} - {resp_conn.text[:150]}")

        # 3. Create workspace
        resp_ws = requests.post(
            "https://api.fabric.microsoft.com/v1/workspaces",
            headers={**fabric_headers, "Content-Type": "application/json"},
            json={"displayName": ws_name, "description": f"Developer workspace for {alias}"},
        )
        if resp_ws.status_code not in (200, 201):
            dev_errors.append(f"Workspace: {resp_ws.status_code} - {resp_ws.text[:150]}")
            all_results.append({"alias": alias, "errors": dev_errors})
            continue
        dev_ws_id = resp_ws.json()["id"]

        # 3a. Assign capacity
        if capacity_id:
            requests.post(
                f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/assignToCapacity",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={"capacityId": capacity_id},
            )

        # 3b. Provision identity
        requests.post(
            f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/provisionIdentity",
            headers=fabric_headers,
        )

        # 3c. Assign domain
        if domain_id:
            requests.post(
                f"https://api.fabric.microsoft.com/v1/admin/domains/{domain_id}/assignWorkspaces",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={"workspacesIds": [dev_ws_id]},
            )

        # 3d. Apply tags (feature instead of main)
        if feature_tag_ids:
            requests.post(
                f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/applyTags",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={"tags": feature_tag_ids},
            )

        # 3e. Replicate role assignments
        for ra in role_assignments:
            principal = ra.get("principal", {})
            if principal.get("type") == "ServicePrincipal":
                continue
            requests.post(
                f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/roleAssignments",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={"principal": {"id": principal["id"], "type": principal["type"]}, "role": ra["role"]},
            )

        # 3f. Create MPEs
        mpe_url = f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/managedPrivateEndpoints"
        mpe_headers = {**fabric_headers, "Content-Type": "application/json"}
        kv_resource_id = settings.get("mpe_keyvault_resource_id", "")
        if kv_resource_id:
            requests.post(mpe_url, headers=mpe_headers, json={
                "name": f"mpe-kv-{ws_name}", "targetPrivateLinkResourceId": kv_resource_id,
                "targetSubresourceType": "vault", "requestMessage": f"Fabric {ws_name}",
            })

        # 4. Git integration
        if dev_conn_id and git_owner and git_repo:
            # Create .gitkeep in folder for the feature branch
            if git_folder and git_folder != "/" and github_pat:
                gitkeep_path = f"{git_folder.strip('/')}/.gitkeep"
                gh_check = requests.get(
                    f"https://api.github.com/repos/{git_owner}/{git_repo}/contents/{gitkeep_path}",
                    headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"},
                    params={"ref": branch_name},
                )
                if gh_check.status_code == 404:
                    import base64
                    requests.put(
                        f"https://api.github.com/repos/{git_owner}/{git_repo}/contents/{gitkeep_path}",
                        headers={"Authorization": f"token {github_pat}", "Accept": "application/vnd.github.v3+json"},
                        json={"message": f"Create folder {git_folder}", "content": base64.b64encode(b"").decode(), "branch": branch_name},
                    )

            resp_git_conn = requests.post(
                f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/git/connect",
                headers={**fabric_headers, "Content-Type": "application/json"},
                json={
                    "gitProviderDetails": {
                        "gitProviderType": "GitHub", "ownerName": git_owner,
                        "repositoryName": git_repo, "branchName": branch_name,
                        "directoryName": git_folder or "/",
                    },
                    "myGitCredentials": {"source": "ConfiguredConnection", "connectionId": dev_conn_id},
                },
            )
            if resp_git_conn.status_code == 200:
                requests.post(
                    f"https://api.fabric.microsoft.com/v1/workspaces/{dev_ws_id}/git/initializeConnection",
                    headers={**fabric_headers, "Content-Type": "application/json"},
                    json={"initializationStrategy": "PreferWorkspace"},
                )
            elif resp_git_conn.status_code != 200:
                dev_errors.append(f"Git connect: {resp_git_conn.status_code} - {resp_git_conn.text[:150]}")

        all_results.append({"alias": alias, "workspace": ws_name, "errors": dev_errors})

    # Flash results
    successes = [r for r in all_results if not r.get("errors")]
    failures = [r for r in all_results if r.get("errors")]
    if successes:
        flash(f"Created {len(successes)} developer workspace(s): {', '.join(r['workspace'] for r in successes)}", "success")
    if failures:
        for f_item in failures:
            flash(f"Errors for {f_item['alias']}: {'; '.join(f_item['errors'])}", "error")

    return redirect(url_for("developer_workspaces"))


@app.route("/workspace-compliance")
def workspace_compliance():
    fabric_headers = get_headers()
    pbi_headers = get_powerbi_headers()
    settings = load_settings()

    workspaces = fetch_workspaces_admin(pbi_headers) or fetch_workspaces(fabric_headers)
    compliance_tag = settings.get("compliance_domain_required_tag", "")

    compliance_data = []
    for ws in workspaces:
        if ws.get("type") and ws["type"] != "Workspace":
            continue

        ws_id = ws["id"]
        ws_name = ws.get("displayName") or ws.get("name", "")

        # Get workspace detail (tags, domainId)
        resp = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}",
            headers=fabric_headers,
        )
        if resp.status_code != 200:
            continue
        detail = resp.json()
        tags = detail.get("tags", [])
        domain_id = detail.get("domainId")
        tag_names = [t.get("displayName", "") for t in tags] if tags else []

        # Check git connection
        resp_git = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/git/connection",
            headers=fabric_headers,
        )
        has_git = resp_git.status_code == 200 and resp_git.json().get("gitProviderDetails")

        # Check workspace identity via Graph API (service principal with workspace name)
        graph_headers = {"Authorization": f"Bearer {get_graph_token()}"}
        resp_sp = requests.get(
            "https://graph.microsoft.com/v1.0/servicePrincipals",
            headers=graph_headers,
            params={"$filter": f"displayName eq '{ws_name}'", "$select": "id,displayName", "$top": "1"},
        )
        has_identity = resp_sp.status_code == 200 and bool(resp_sp.json().get("value"))

        # Check Log Analytics and users from PBI admin API
        has_log_analytics = False
        resp_pbi_ws = requests.get(
            f"https://api.powerbi.com/v1.0/myorg/admin/groups/{ws_id}",
            headers=pbi_headers,
        )
        if resp_pbi_ws.status_code == 200:
            has_log_analytics = bool(resp_pbi_ws.json().get("logAnalyticsWorkspace"))

        # Check managed private endpoints
        resp_mpe = requests.get(
            f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/managedPrivateEndpoints",
            headers=fabric_headers,
        )
        mpe_list = resp_mpe.json().get("value", []) if resp_mpe.status_code == 200 else []
        kv_mpe = None
        for mpe in mpe_list:
            if "vault" in (mpe.get("targetSubresourceType") or "").lower():
                kv_mpe = mpe
                break
        kv_mpe_status = None
        if kv_mpe:
            conn_state = kv_mpe.get("connectionState", {})
            kv_mpe_status = conn_state.get("status", kv_mpe.get("provisioningState", "Unknown"))

        # Domain required check
        requires_domain = compliance_tag and any(compliance_tag.lower() in t.lower() for t in tag_names)
        has_domain = bool(domain_id)

        compliance_data.append({
            "name": ws_name,
            "id": ws_id,
            "has_git": has_git,
            "has_identity": has_identity,
            "kv_mpe_status": kv_mpe_status,
            "has_log_analytics": has_log_analytics,
            "has_domain": has_domain,
            "requires_domain": requires_domain,
            "tags": tag_names,
        })

    return render_template(
        "workspace_compliance.html",
        compliance_data=compliance_data,
        compliance_tag=compliance_tag,
    )


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        settings = {
            "environments": [x.strip() for x in request.form.get("environments", "").split(",") if x.strip()],
            "branches": [x.strip() for x in request.form.get("branches", "").split(",") if x.strip()],
            "mpe_cognitive_services_resource_id": request.form.get("mpe_cognitive_services_resource_id", "").strip(),
            "mpe_keyvault_resource_id": request.form.get("mpe_keyvault_resource_id", "").strip(),
            "compliance_domain_required_tag": request.form.get("compliance_domain_required_tag", "").strip(),
        }
        save_settings(settings)
        flash("Settings saved.", "success")
        return redirect(url_for("settings_page"))

    return render_template("settings.html", settings=load_settings())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
