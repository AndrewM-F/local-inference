# Runs the stack at boot, without needing an interactive login.
#
#   .\scripts\register-autostart.ps1
#   .\scripts\register-autostart.ps1 -User "DOMAIN\you" -TaskName my-inference
param(
  [string]$TaskName = "local-inference-stack",
  [string]$User = $env:USERNAME,
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" })
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\start-stack.ps1"

$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
# S4U runs whether or not anyone is logged in; the GPU is still visible to it.
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit 0 `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
  -Principal $principal -Settings $settings -Force | Out-Null
Register-ScheduledTask -TaskName "$TaskName-startup" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
  -Principal $principal -Settings $settings -Force | Out-Null
"registered $TaskName (at startup, S4U) for $User"
Start-ScheduledTask -TaskName $TaskName
