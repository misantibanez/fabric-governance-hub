$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$InformationPreference = "SilentlyContinue"

Import-Module DataGateway.Profile -ErrorAction Stop 3>$null 4>$null 6>$null
Import-Module DataGateway -ErrorAction Stop 3>$null 4>$null 6>$null

$InformationPreference = "Continue"

$script:GatewayConnected = $false

function Write-GatewayResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequestId,

        [Parameter(Mandatory = $true)]
        [string]$Operation,

        [Parameter(Mandatory = $true)]
        [bool]$Ok,

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
    $json = $response | ConvertTo-Json -Depth 12 -Compress
    [Console]::Out.WriteLine("@@GATEWAY_RESULT@@$json")
    [Console]::Out.Flush()
}

function Assert-GatewayConnection {
    if (-not $script:GatewayConnected) {
        throw "Connect to the Data Gateway service before running this operation."
    }
}

function Get-GatewayGovernanceState {
    Assert-GatewayConnection

    $tenantPolicy = Get-DataGatewayTenantPolicy
    $policyValue = [int]$tenantPolicy.Policy
    $policy = [ordered]@{
        PersonalGatewayInstallPolicy = if (($policyValue -band 1) -eq 1) { "Restricted" } else { "Open" }
        ResourceGatewayInstallPolicy = if (($policyValue -band 2) -eq 2) { "Restricted" } else { "Open" }
        RawPolicy = $policyValue
        TenantObjectId = [string]$tenantPolicy.TenantObjectId
    }
    $installers = @(Get-DataGatewayInstaller)
    $clusters = @(Get-DataGatewayCluster)

    return [ordered]@{
        policy = $policy
        installers = $installers
        clusters = $clusters
        capturedAt = [DateTimeOffset]::UtcNow.ToString("o")
    }
}

[Console]::Out.WriteLine("@@GATEWAY_READY@@")
[Console]::Out.Flush()

while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    $requestId = "unknown"
    $operation = "unknown"
    try {
        $request = $line | ConvertFrom-Json -Depth 20
        $requestId = [string]$request.requestId
        $operation = [string]$request.operation
        $parameters = $request.parameters

        switch ($operation) {
            "connect_gateway" {
                Login-DataGatewayServiceAccount -ForceDeviceCodeAuthentication $true | Out-Null
                $script:GatewayConnected = $true
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $null
            }
            "connection_status" {
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data ([ordered]@{
                    gatewayConnected = $script:GatewayConnected
                })
            }
            "get_state" {
                $state = Get-GatewayGovernanceState
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $state
            }
            "set_policy" {
                Assert-GatewayConnection
                $gatewayType = [string]$parameters.gatewayType
                $policy = [string]$parameters.policy
                if ($policy -notin @("None", "Open", "Restricted")) {
                    throw "Policy must be None, Open, or Restricted."
                }
                if ($gatewayType -eq "Personal") {
                    Set-DataGatewayTenantPolicy -PersonalGatewayInstallPolicy $policy
                } elseif ($gatewayType -eq "Resource") {
                    Set-DataGatewayTenantPolicy -ResourceGatewayInstallPolicy $policy
                } else {
                    throw "Gateway type must be Personal or Resource."
                }
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data (Get-GatewayGovernanceState)
            }
            "add_installers" {
                Assert-GatewayConnection
                $principalIds = @($parameters.principalObjectIds | ForEach-Object { [string]$_ })
                if ($principalIds.Count -eq 0) {
                    throw "No users were supplied. The installer list was not changed."
                }
                Set-DataGatewayInstaller -PrincipalObjectIds $principalIds -Operation Add -GatewayType Resource
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data ([ordered]@{
                    state = Get-GatewayGovernanceState
                })
            }
            "remove_installers" {
                Assert-GatewayConnection
                $principalIds = @($parameters.principalObjectIds | ForEach-Object { [string]$_ })
                if ($principalIds.Count -eq 0) {
                    throw "Select at least one installer to remove."
                }
                foreach ($principalId in $principalIds) {
                    if ($principalId -notmatch "^[0-9a-fA-F-]{36}$") {
                        throw "Invalid principal Object ID: $principalId"
                    }
                }
                Set-DataGatewayInstaller -PrincipalObjectIds $principalIds -Operation Remove -GatewayType Resource
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data (Get-GatewayGovernanceState)
            }
            "disconnect" {
                Disconnect-DataGatewayServiceAccount -ErrorAction SilentlyContinue | Out-Null
                $script:GatewayConnected = $false
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $null
            }
            "exit" {
                Disconnect-DataGatewayServiceAccount -ErrorAction SilentlyContinue | Out-Null
                Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $true -Data $null
                break
            }
            default {
                throw "Unsupported gateway operation: $operation"
            }
        }

        if ($operation -eq "exit") {
            break
        }
    } catch {
        Write-GatewayResult -RequestId $requestId -Operation $operation -Ok $false -ErrorMessage $_.Exception.Message
    }
}
