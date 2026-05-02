param(
    [string]$TaskName = "VibeFlow Core"
)

$ErrorActionPreference = "Stop"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Windows startup task kaldirildi: $TaskName"
