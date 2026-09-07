[CmdletBinding()]
param(
    [Parameter()]
    [string]$Destination = (Join-Path ([System.IO.Path]::GetTempPath()) 'fabric-governance-hub-acr')
)

$ErrorActionPreference = 'Stop'
$infraPath = $PSScriptRoot
$repoPath = Split-Path -Parent $infraPath

if (Test-Path $Destination) {
    Remove-Item -Recurse -Force $Destination
}

New-Item -ItemType Directory -Path $Destination | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Destination 'infra') | Out-Null
Copy-Item (Join-Path $infraPath 'Dockerfile') (Join-Path $Destination 'infra')
Copy-Item (Join-Path $infraPath '.dockerignore') $Destination
Copy-Item (Join-Path $infraPath 'requirements.azure.txt') (Join-Path $Destination 'infra')
Copy-Item (Join-Path $repoPath 'app.py') $Destination
Copy-Item (Join-Path $repoPath 'gateway_session.py') $Destination
Copy-Item (Join-Path $repoPath 'mpe_validation.py') $Destination
Copy-Item (Join-Path $repoPath 'settings_repository.py') $Destination
Copy-Item (Join-Path $repoPath 'workspace_deletion.py') $Destination
Copy-Item -Recurse (Join-Path $repoPath 'scripts') $Destination
Copy-Item -Recurse (Join-Path $repoPath 'templates') $Destination

Write-Output $Destination