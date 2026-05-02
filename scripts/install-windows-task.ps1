param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$TaskName = "VibeFlow Core",
    [int]$Port = 7400
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Launcher = Join-Path $RepoRoot "vibeflow.ps1"

if (-not (Test-Path $Launcher)) {
    throw "Launcher bulunamadi: $Launcher"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`" -ProjectRoot `"$ProjectRoot`" -Port $Port"

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Description "Starts VibeFlow Core local context sidecar and watches $ProjectRoot" `
    -Force

Write-Host "Windows startup task kuruldu: $TaskName"
Write-Host "Proje: $ProjectRoot"
Write-Host "API: http://127.0.0.1:$Port"
