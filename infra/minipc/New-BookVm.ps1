# Run in elevated PowerShell ONLY after explicit VM creation approval.
#Requires -RunAsAdministrator
param(
  [Parameter(Mandatory)][string]$IsoPath,
  [Parameter(Mandatory)][string]$VmRoot,
  [string]$SeedIsoPath,
  [string]$SwitchName = 'Default Switch'
)
$ErrorActionPreference = 'Stop'
$vmName = 'bookmembers-ubuntu'
if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) { throw 'VM already exists; inspect before reuse.' }
if (!(Test-Path -LiteralPath $IsoPath -PathType Leaf)) { throw 'Verified Ubuntu 24.04 server ISO required.' }
if ($SeedIsoPath -and !(Test-Path -LiteralPath $SeedIsoPath -PathType Leaf)) { throw 'Seed ISO missing.' }
Get-VMSwitch -Name $SwitchName | Out-Null
$vmDirectory = Join-Path ([IO.Path]::GetFullPath($VmRoot)) $vmName
if (Test-Path -LiteralPath $vmDirectory) { throw 'Destination already exists; refusing to overwrite.' }
New-Item -ItemType Directory -Path $vmDirectory | Out-Null
New-VM -Name $vmName -Generation 2 -MemoryStartupBytes 1536MB -Path $vmDirectory -NewVHDPath (Join-Path $vmDirectory 'system.vhdx') -NewVHDSizeBytes 30GB -SwitchName $SwitchName | Out-Null
Set-VMProcessor -VMName $vmName -Count 2
Set-VMMemory -VMName $vmName -DynamicMemoryEnabled $true -MinimumBytes 1GB -StartupBytes 1536MB -MaximumBytes 3GB
Set-VM -Name $vmName -AutomaticStartAction Start -AutomaticStartDelay 30 -AutomaticStopAction ShutDown -AutomaticCheckpointsEnabled $false
Set-VMFirmware -VMName $vmName -EnableSecureBoot On -SecureBootTemplate MicrosoftUEFICertificateAuthority
$dvd = Add-VMDvdDrive -VMName $vmName -Path ([IO.Path]::GetFullPath($IsoPath)) -Passthru
Set-VMFirmware -VMName $vmName -FirstBootDevice $dvd
if ($SeedIsoPath) {
  Add-VMDvdDrive -VMName $vmName -Path ([IO.Path]::GetFullPath($SeedIsoPath)) | Out-Null
}
# Start/installation is a separate explicit step. No Windows networking or power settings changed.
