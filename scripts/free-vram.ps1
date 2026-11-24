# Stops the resident services so an exclusive job (video, 3D) owns the GPU.
# start-stack.ps1 brings them back afterwards.
#
#   .\scripts\free-vram.ps1
#   .\scripts\free-vram.ps1 -Root D:\ai -Keep 8080
param(
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" }),
  [int[]]$Keep = @()
)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$config = Get-Content (Join-Path $repo "config\models.json") -Raw | ConvertFrom-Json
foreach ($svc in $config.services.PSObject.Properties) {
  $port = $svc.Value.port
  if (-not $port -or $Keep -contains $port) { continue }
  Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep 3
$os = Get-CimInstance Win32_OperatingSystem
"freed; free RAM = {0:N1} GB" -f ($os.FreePhysicalMemory / 1MB)
