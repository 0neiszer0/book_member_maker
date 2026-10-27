#Requires -RunAsAdministrator
# Run ONLY after explicit host-feature approval. Never reboots automatically.
param([Parameter(Mandatory)][string]$ResultPath)
$ErrorActionPreference = 'Stop'
try {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
    if ($feature.State -eq 'Enabled') {
        $result = @{Success=$true; State='Enabled'; RestartNeeded=$false}
    } else {
        $change = Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -NoRestart
        $result = @{Success=$true; State='Enabled'; RestartNeeded=$change.RestartNeeded}
    }
    $result | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath $ResultPath
} catch {
    @{Success=$false; Error=$_.Exception.Message} | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath $ResultPath
    exit 1
}
Write-Output 'Stop here. Reboot requires separate user approval.'
