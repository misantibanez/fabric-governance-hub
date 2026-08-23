$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$InformationPreference = "SilentlyContinue"

Import-Module Az.Accounts -ErrorAction Stop 3>$null 4>$null 6>$null
Import-Module Az.Resources -ErrorAction Stop 3>$null 4>$null 6>$null

$InformationPreference = "Continue"
Disable-AzContextAutosave -Scope Process | Out-Null
Clear-AzContext -Scope Process -Force -ErrorAction SilentlyContinue
$script:AzureConnected = $false

function Write-GatewayResult {
    param(
        [Parameter(Mandatory = $true)][string]$RequestId,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][bool]$Ok,
        [object]$Data = $null,
        [string]$ErrorMessage = $null
    )

    $response = [ordered]@{
        requestId = $RequestId
        operation = $Operation
        ok = $Ok
        data = $Data
        error = $ErrorMessage
    }
    [Console]::Out.WriteLine("@@GATEWAY_RESULT@@$(($response | ConvertTo-Json -Depth 12 -Compress))")
    [Console]::Out.Flush()
}

function Assert-AzureConnection {
    if (-not $script:AzureConnected -or -not (Get-AzContext -ErrorAction SilentlyContinue)) {
        throw "Connect to Azure before resolving users or groups."
    }
}

function Resolve-AuthorizedUsers {
    param([string[]]$UserPrincipalNames, [string[]]$GroupNames)

    Assert-AzureConnection
    $objectIds = [System.Collections.Generic.HashSet[string]]::new()
    $processedGroupIds = [System.Collections.Generic.HashSet[string]]::new()
    $resolvedUsers = [System.Collections.Generic.List[object]]::new()
    $unresolved = [System.Collections.Generic.List[string]]::new()

    function Add-ResolvedUser {
        param([Parameter(Mandatory = $true)][string]$ObjectId, [Parameter(Mandatory = $true)][string]$Source)
        $user = Get-AzADUser -ObjectId $ObjectId -ErrorAction SilentlyContinue
        if (-not $user) { return $false }
        if ($objectIds.Add([string]$user.Id)) {
            $resolvedUsers.Add([ordered]@{
                id = [string]$user.Id
                displayName = [string]$user.DisplayName
                userPrincipalName = [string]$user.UserPrincipalName
                source = $Source
            })
        }
        return $true
    }

    function Add-GroupMembers {
        param([Parameter(Mandatory = $true)][string]$GroupObjectId, [Parameter(Mandatory = $true)][string]$GroupName)
        if (-not $processedGroupIds.Add($GroupObjectId)) { return }
        foreach ($member in @(Get-AzADGroupMember -GroupObjectId $GroupObjectId -ErrorAction SilentlyContinue)) {
            $memberId = [string]$member.Id
            if (Add-ResolvedUser -ObjectId $memberId -Source "group: $GroupName") { continue }
            $nestedGroup = Get-AzADGroup -ObjectId $memberId -ErrorAction SilentlyContinue
            if ($nestedGroup) {
                Add-GroupMembers -GroupObjectId ([string]$nestedGroup.Id) -GroupName ([string]$nestedGroup.DisplayName)
            }
        }
    }

    foreach ($upn in @($UserPrincipalNames)) {
        if ([string]::IsNullOrWhiteSpace($upn)) { continue }
        $user = Get-AzADUser -UserPrincipalName $upn.Trim() -ErrorAction SilentlyContinue
        if ($user) {
            [void](Add-ResolvedUser -ObjectId ([string]$user.Id) -Source "direct user")
        } else {
            $unresolved.Add("User: $upn")
        }
    }

    foreach ($groupName in @($GroupNames)) {
        if ([string]::IsNullOrWhiteSpace($groupName)) { continue }
        $groups = @(Get-AzADGroup -DisplayName $groupName.Trim() -ErrorAction SilentlyContinue)
        if ($groups.Count -eq 0) {
            $unresolved.Add("Group: $groupName")
            continue
        }
        foreach ($group in $groups) {
            Add-GroupMembers -GroupObjectId ([string]$group.Id) -GroupName ([string]$group.DisplayName)
        }
    }

    return [ordered]@{
        principalObjectIds = @($objectIds)
        users = @($resolvedUsers)
        unresolved = @($unresolved)
    }
}

[Console]::Out.WriteLine("@@GATEWAY_READY@@")
[Console]::Out.Flush()

while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $requestId = "unknown"
    $operation = "unknown"
    try {
        $request = $line | ConvertFrom-Json -Depth 20
        $requestId = [string]$request.requestId
        $operation = [string]$request.operation
        $parameters = $request.parameters

        switch ($operation) {
            "connect_azure" {
                $tenantId = [string]$parameters.tenantId
                if ([string]::IsNullOrWhiteSpace($tenantId)) { throw "Tenant ID is required." }
                Connect-AzAccount -Tenant $tenantId -UseDeviceAuthentication | Out-Null
                $context = Get-AzContext
                $script:AzureConnected = $null -ne $context
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data ([ordered]@{
                    account = [string]$context.Account.Id
                    tenantId = [string]$context.Tenant.Id
                })
            }
            "connection_status" {
                $context = Get-AzContext -ErrorAction SilentlyContinue
                $script:AzureConnected = $null -ne $context
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data ([ordered]@{
                    azureConnected = $script:AzureConnected
                    azureAccount = if ($context) { [string]$context.Account.Id } else { $null }
                    tenantId = if ($context) { [string]$context.Tenant.Id } else { $null }
                })
            }
            "resolve_principals" {
                $resolved = Resolve-AuthorizedUsers -UserPrincipalNames @($parameters.users) -GroupNames @($parameters.groups)
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $resolved
            }
            "resolve_object_ids" {
                Assert-AzureConnection
                $users = [System.Collections.Generic.List[object]]::new()
                foreach ($objectId in @($parameters.principalObjectIds)) {
                    $principalId = [string]$objectId
                    if ($principalId -notmatch "^[0-9a-fA-F-]{36}$") { continue }
                    $user = Get-AzADUser -ObjectId $principalId -ErrorAction SilentlyContinue
                    $users.Add([ordered]@{
                        id = $principalId
                        displayName = if ($user) { [string]$user.DisplayName } else { $null }
                        userPrincipalName = if ($user) { [string]$user.UserPrincipalName } else { $null }
                    })
                }
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data ([ordered]@{
                    users = @($users)
                })
            }
            "disconnect" {
                Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
                $script:AzureConnected = $false
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $null
            }
            "exit" {
                Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $null
                break
            }
            default { throw "Unsupported Azure identity operation: $operation" }
        }
        if ($operation -eq "exit") { break }
    } catch {
        Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $false -ErrorMessage $_.Exception.Message
    }
}
