import json

from flask import jsonify, render_template, request


CAPACITIES = [
    {"id": "capacity-east", "displayName": "Analytics East", "sku": "F64", "region": "East US", "state": "Active"},
    {"id": "capacity-west", "displayName": "Data Products West", "sku": "F32", "region": "West Europe", "state": "Active"},
    {"id": "capacity-central", "displayName": "Enterprise Central", "sku": "F128", "region": "Central US", "state": "Active"},
    {"id": "capacity-sandbox", "displayName": "Innovation Sandbox", "sku": "F16", "region": "East US 2", "state": "Suspended"},
]
DOMAINS = [
    {"id": "domain-finance", "displayName": "Finance", "description": "Financial reporting and planning", "parentDomainId": None, "parentName": ""},
    {"id": "domain-sales", "displayName": "Sales", "description": "Commercial performance and forecasting", "parentDomainId": None, "parentName": ""},
    {"id": "domain-operations", "displayName": "Operations", "description": "Supply chain and operational analytics", "parentDomainId": None, "parentName": ""},
    {"id": "domain-people", "displayName": "People", "description": "Workforce and organizational insights", "parentDomainId": None, "parentName": ""},
    {"id": "domain-reporting", "displayName": "Reporting", "description": "Certified financial reporting", "parentDomainId": "domain-finance", "parentName": "Finance"},
    {"id": "domain-planning", "displayName": "Planning", "description": "Budget and forecast models", "parentDomainId": "domain-finance", "parentName": "Finance"},
    {"id": "domain-supply-chain", "displayName": "Supply Chain", "description": "Inventory, logistics, and fulfillment", "parentDomainId": "domain-operations", "parentName": "Operations"},
]
TAGS = [
    {"id": "tag-main", "displayName": "Main", "description": "Source workspace", "scope": {"type": "Tenant"}},
    {"id": "tag-dev", "displayName": "Dev", "description": "Development", "scope": {"type": "Tenant"}},
    {"id": "tag-int", "displayName": "Int", "description": "Integration testing", "scope": {"type": "Tenant"}},
    {"id": "tag-prd", "displayName": "Prd", "description": "Production", "scope": {"type": "Tenant"}},
    {"id": "tag-dhub", "displayName": "DHUB", "description": "Governed data product", "scope": {"type": "Tenant"}},
    {"id": "tag-pii", "displayName": "PII", "description": "Contains personal information", "scope": {"type": "Tenant"}},
    {"id": "tag-reference", "displayName": "Reference Assets", "description": "Shared reference data", "scope": {"type": "Tenant"}},
    {"id": "tag-certified", "displayName": "Certified", "description": "Certified for enterprise use", "scope": {"type": "Tenant"}},
    {"id": "tag-sandbox", "displayName": "Sandbox", "description": "Experimental workload", "scope": {"type": "Tenant"}},
]
WORKSPACES = [
    {"id": "workspace-finance", "displayName": "Finance Analytics", "name": "Finance Analytics", "type": "Workspace", "state": "Active", "capacityId": "capacity-east", "domainId": "domain-reporting", "tags": [TAGS[0], TAGS[3], TAGS[4], TAGS[7]], "git_owner": "contoso", "git_repo": "finance-analytics", "git_folder": "/fabric"},
    {"id": "workspace-finance-int", "displayName": "Finance Analytics Int", "name": "Finance Analytics Int", "type": "Workspace", "state": "Active", "capacityId": "capacity-east", "domainId": "domain-reporting", "tags": [TAGS[2], TAGS[4]]},
    {"id": "workspace-budget", "displayName": "Budget Planning", "name": "Budget Planning", "type": "Workspace", "state": "Active", "capacityId": "capacity-central", "domainId": "domain-planning", "tags": [TAGS[0], TAGS[3], TAGS[4]], "git_owner": "contoso", "git_repo": "budget-planning", "git_folder": "/fabric"},
    {"id": "workspace-sales", "displayName": "Sales Insights", "name": "Sales Insights", "type": "Workspace", "state": "Active", "capacityId": "capacity-west", "domainId": "domain-sales", "tags": [TAGS[0], TAGS[3], TAGS[7]], "git_owner": "contoso", "git_repo": "sales-insights", "git_folder": "/workspace"},
    {"id": "workspace-sales-dev", "displayName": "Sales Insights Dev", "name": "Sales Insights Dev", "type": "Workspace", "state": "Active", "capacityId": "capacity-west", "domainId": "domain-sales", "tags": [TAGS[1]]},
    {"id": "workspace-customer-pii", "displayName": "Customer PII Analytics", "name": "Customer PII Analytics", "type": "Workspace", "state": "Active", "capacityId": "capacity-central", "domainId": "domain-sales", "tags": [TAGS[3], TAGS[4], TAGS[5]]},
    {"id": "workspace-supply", "displayName": "Supply Chain Control Tower", "name": "Supply Chain Control Tower", "type": "Workspace", "state": "Active", "capacityId": "capacity-central", "domainId": "domain-supply-chain", "tags": [TAGS[0], TAGS[3], TAGS[4]], "git_owner": "contoso", "git_repo": "supply-chain", "git_folder": "/control-tower"},
    {"id": "workspace-inventory", "displayName": "Inventory Reference Assets", "name": "Inventory Reference Assets", "type": "Workspace", "state": "Active", "capacityId": "capacity-west", "domainId": "domain-supply-chain", "tags": [TAGS[3], TAGS[6], TAGS[7]]},
    {"id": "workspace-people", "displayName": "People Analytics PII", "name": "People Analytics PII", "type": "Workspace", "state": "Active", "capacityId": "capacity-east", "domainId": "domain-people", "tags": [TAGS[0], TAGS[3], TAGS[4], TAGS[5]], "git_owner": "contoso", "git_repo": "people-analytics", "git_folder": "/fabric"},
    {"id": "workspace-executive", "displayName": "Executive KPI Scorecard", "name": "Executive KPI Scorecard", "type": "Workspace", "state": "Active", "capacityId": "capacity-central", "domainId": "domain-finance", "tags": [TAGS[3], TAGS[7]]},
    {"id": "workspace-sandbox", "displayName": "Developer Sandbox", "name": "Developer Sandbox", "type": "Workspace", "state": "Active", "capacityId": "capacity-sandbox", "domainId": None, "tags": [TAGS[1], TAGS[8]]},
    {"id": "workspace-legacy", "displayName": "Legacy BI Migration", "name": "Legacy BI Migration", "type": "Workspace", "state": "Inactive", "capacityId": "capacity-sandbox", "domainId": None, "tags": [TAGS[2], TAGS[8]]},
    {"id": "workspace-personal", "displayName": "Avery Morgan", "name": "Avery Morgan", "type": "PersonalGroup", "state": "Active", "capacityId": "capacity-east", "domainId": None, "tags": []},
]
CONNECTIONS = [
    {"id": "connection-github", "displayName": "GitHub - Contoso Analytics", "connectionDetails": {"type": "GitHub"}, "connectivityType": "ShareableCloud", "credentialDetails": {"credentialType": "OAuth2"}, "privacyLevel": "Organizational"},
    {"id": "connection-sql", "displayName": "Finance SQL Warehouse", "connectionDetails": {"type": "SQL"}, "connectivityType": "OnPremisesGateway", "credentialDetails": {"credentialType": "Windows"}, "privacyLevel": "Organizational"},
    {"id": "connection-snowflake", "displayName": "Sales Snowflake", "connectionDetails": {"type": "Snowflake"}, "connectivityType": "ShareableCloud", "credentialDetails": {"credentialType": "KeyPair"}, "privacyLevel": "Organizational"},
    {"id": "connection-adls", "displayName": "Enterprise Data Lake", "connectionDetails": {"type": "AzureDataLakeStorage"}, "connectivityType": "ShareableCloud", "credentialDetails": {"credentialType": "ServicePrincipal"}, "privacyLevel": "Organizational"},
    {"id": "connection-sap", "displayName": "SAP Operations", "connectionDetails": {"type": "SAPBW"}, "connectivityType": "OnPremisesGateway", "credentialDetails": {"credentialType": "Basic"}, "privacyLevel": "Private"},
]
GATEWAYS = [
    {"id": "gateway-enterprise", "displayName": "Enterprise Gateway", "name": "Enterprise Gateway", "type": "OnPremises", "version": "3000.246.8", "numberOfMemberGateways": 3, "contactInfo": "data-platform@contoso.example", "users": "Data Platform Admins (Admin); BI Operations (User)", "datasources": [{"id": "source-sql", "datasourceName": "Finance SQL", "datasourceType": "SQL"}, {"id": "source-sap", "datasourceName": "SAP Operations", "datasourceType": "SAPBW"}]},
    {"id": "gateway-europe", "displayName": "Europe Regional Gateway", "name": "Europe Regional Gateway", "type": "OnPremises", "version": "3000.246.8", "numberOfMemberGateways": 2, "contactInfo": "eu-data@contoso.example", "users": "EU Data Stewards (Admin)", "datasources": [{"id": "source-eu-sql", "datasourceName": "EU Sales SQL", "datasourceType": "SQL"}]},
    {"id": "gateway-vnet", "displayName": "Managed VNet Gateway", "name": "Managed VNet Gateway", "type": "VirtualNetwork", "capacityId": "capacity-central", "inactivityMinutesBeforeSleep": 30, "virtualNetworkAzureResource": {"virtualNetworkName": "vnet-analytics", "subnetName": "snet-data"}, "contactInfo": "cloud-platform@contoso.example", "users": "Cloud Platform (Admin)", "datasources": [{"id": "source-adls", "datasourceName": "Enterprise Data Lake", "datasourceType": "AzureDataLakeStorage"}]},
]
SETTINGS = {
    "environments": ["Dev", "Int", "Prd"],
    "branches": ["feature", "main"],
    "mpe_cognitive_services_resource_id": "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.CognitiveServices/accounts/ai-demo",
    "mpe_keyvault_resource_id": "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.KeyVault/vaults/kv-demo",
    "workspace_monitoring_required": True,
    "log_analytics_workspace_resource_id": "/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.OperationalInsights/workspaces/log-demo",
    "fabric_monitoring_api_base_url": "https://demo.invalid",
    "fabric_workspace_monitoring_enabled": False,
    "compliance_domain_required_tag": "DHUB",
}


def _workspace_context():
    roots = [domain for domain in DOMAINS if not domain["parentDomainId"]]
    children = [domain for domain in DOMAINS if domain["parentDomainId"]]
    domain_map = {domain["id"]: domain["displayName"] for domain in DOMAINS}
    capacity_map = {item["id"]: item["displayName"] for item in CAPACITIES}
    return roots, children, domain_map, capacity_map


def _permission_result(query):
    return {
        "principal": {"id": "demo-user", "displayName": "Avery Morgan", "type": "User", "userPrincipalName": query},
        "effectivePrincipalCount": 4,
        "workspaceCount": 4,
        "lakehouseCount": 5,
        "warnings": ["One workspace returned a partial OneLake role assignment result."],
        "workspaces": [
            {"id": "workspace-finance", "name": "Finance Analytics", "roles": [{"role": "Viewer", "sourceName": "Finance Readers", "direct": False}], "lakehouses": [{"id": "lakehouse-ledger", "name": "Finance Ledger", "workspaceInherited": True, "roles": [{"role": "Ledger Readers", "actions": ["Read"], "paths": ["Tables/Ledger"], "sourceName": "Finance Readers", "direct": False}]}]},
            {"id": "workspace-sales", "name": "Sales Insights", "roles": [{"role": "Contributor", "sourceName": "Avery Morgan", "direct": True}], "lakehouses": [{"id": "lakehouse-sales", "name": "Sales Curated", "workspaceInherited": True, "roles": []}]},
            {"id": "workspace-customer-pii", "name": "Customer PII Analytics", "roles": [{"role": "Viewer", "sourceName": "Commercial Analytics", "direct": False}], "lakehouses": [{"id": "lakehouse-customer", "name": "Customer 360", "workspaceInherited": False, "roles": [{"role": "Masked Customer Reader", "actions": ["Read", "ReadAll"], "paths": ["Tables/Customer", "Tables/Consent"], "sourceName": "Commercial Analytics", "direct": False}]}, {"id": "lakehouse-campaign", "name": "Campaign Performance", "workspaceInherited": True, "roles": []}]},
            {"id": "workspace-supply", "name": "Supply Chain Control Tower", "roles": [{"role": "Member", "sourceName": "Operations Leads", "direct": False}], "lakehouses": [{"id": "lakehouse-supply", "name": "Supply Chain Curated", "workspaceInherited": True, "roles": [{"role": "Regional Operations", "actions": ["Read"], "paths": ["Tables/Inventory", "Tables/Shipments"], "sourceName": "Operations Leads", "direct": False}]}]},
        ],
    }


def render_demo_endpoint(endpoint):
    roots, children, domain_map, capacity_map = _workspace_context()
    if endpoint in {"menu", None}:
        return None
    if endpoint == "gateway_governance":
        return render_template("gateway_governance.html", tenant_id="demo-tenant")
    if endpoint == "gateway_governance_status":
        state = {"running": False, "busy": False, "azureConnected": False, "gatewayConnected": False}
        return jsonify({"ok": True, "azure": state, "gateway": state})
    if endpoint == "gateway_governance_state":
        return jsonify({"ok": True, "state": {"policies": [], "installers": []}})
    if endpoint == "create_workspace_form":
        return render_template("index.html", capacities=CAPACITIES, domains=roots, subdomains=children, tags=TAGS, git_connections=[CONNECTIONS[0]], settings=SETTINGS)
    if endpoint == "tenant_overview":
        return render_template("tenant_overview.html", capacities=CAPACITIES, workspaces=WORKSPACES, domains=roots, subdomains=children, tags=TAGS, gateways=GATEWAYS, connections=CONNECTIONS, domain_map=domain_map)
    if endpoint == "get_domain_tags":
        return jsonify(TAGS)
    if endpoint == "workspace_map":
        return render_template("workspace_map.html", workspaces=WORKSPACES, capacities=CAPACITIES, domains=roots, subdomains=children, tags=TAGS, workspaces_json=json.dumps(WORKSPACES), domain_map_json=json.dumps(domain_map), capacity_map_json=json.dumps(capacity_map), settings=SETTINGS)
    if endpoint == "modify_workspaces":
        return render_template("modify_workspaces.html", workspaces=WORKSPACES, capacities=CAPACITIES, domains=roots, subdomains=children, tags=TAGS, domain_map=domain_map, deletion_review_token="demo-disabled")
    if endpoint == "developer_workspaces":
        main_workspaces = [workspace for workspace in WORKSPACES if any(tag["displayName"] == "Main" for tag in workspace["tags"])]
        return render_template("developer_workspaces.html", main_workspaces=main_workspaces, capacity_map_json=json.dumps(capacity_map), domain_map_json=json.dumps(domain_map), settings=SETTINGS)
    if endpoint == "workspace_compliance":
        compliance = [
            {"name": "Finance Analytics", "id": "workspace-finance", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Main", "Prd", "DHUB"]},
            {"name": "Finance Analytics Int", "id": "workspace-finance-int", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Int", "DHUB"]},
            {"name": "Budget Planning", "id": "workspace-budget", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Main", "Prd", "DHUB"]},
            {"name": "Sales Insights", "id": "workspace-sales", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": False, "tags": ["Main", "Prd", "Certified"]},
            {"name": "Sales Insights Dev", "id": "workspace-sales-dev", "has_git": True, "has_identity": False, "kv_mpe_status": "Pending", "has_log_analytics": False, "has_domain": True, "requires_domain": False, "tags": ["Dev"]},
            {"name": "Customer PII Analytics", "id": "workspace-customer-pii", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Prd", "DHUB", "PII"]},
            {"name": "Supply Chain Control Tower", "id": "workspace-supply", "has_git": True, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Main", "Prd", "DHUB"]},
            {"name": "Inventory Reference Assets", "id": "workspace-inventory", "has_git": False, "has_identity": True, "kv_mpe_status": "Approved", "has_log_analytics": True, "has_domain": True, "requires_domain": False, "tags": ["Prd", "Reference Assets", "Certified"]},
            {"name": "People Analytics PII", "id": "workspace-people", "has_git": True, "has_identity": True, "kv_mpe_status": "Rejected", "has_log_analytics": True, "has_domain": True, "requires_domain": True, "tags": ["Main", "Prd", "DHUB", "PII"]},
            {"name": "Executive KPI Scorecard", "id": "workspace-executive", "has_git": False, "has_identity": True, "kv_mpe_status": None, "has_log_analytics": True, "has_domain": True, "requires_domain": False, "tags": ["Prd", "Certified"]},
            {"name": "Developer Sandbox", "id": "workspace-sandbox", "has_git": False, "has_identity": False, "kv_mpe_status": None, "has_log_analytics": False, "has_domain": False, "requires_domain": False, "tags": ["Dev", "Sandbox"]},
            {"name": "Legacy BI Migration", "id": "workspace-legacy", "has_git": False, "has_identity": False, "kv_mpe_status": "Pending", "has_log_analytics": False, "has_domain": False, "requires_domain": False, "tags": ["Int", "Sandbox"]},
        ]
        return render_template("workspace_compliance.html", compliance_data=compliance, compliance_tag="DHUB")
    if endpoint == "permission_audit":
        query = request.args.get("principal", "").strip()
        return render_template("permission_audit.html", query=query, result=_permission_result(query) if query else None, error=None)
    if endpoint == "settings_page":
        return render_template("settings.html", settings=SETTINGS, settings_etag="demo-read-only")
    if endpoint == "refresh_auth_session":
        return None
    return None