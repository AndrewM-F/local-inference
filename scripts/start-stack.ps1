# Starts the resident stack described by config/models.json.
# Idempotent: a service whose port is already listening is left alone.
#
#   .\scripts\start-stack.ps1
#   .\scripts\start-stack.ps1 -Root D:\ai -Bind 0.0.0.0
param(
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" }),
  [string]$Bind = $(if ($env:INFERENCE_BIND) { $env:INFERENCE_BIND } else { "0.0.0.0" }),
  [int]$Port = $(if ($env:INFERENCE_PORT) { [int]$env:INFERENCE_PORT } else { 8080 }),
  # Client networks allowed through the firewall. LocalSubnet covers the LAN;
  # add your VPN/CGNAT range if clients reach the gateway that way.
  [string[]]$AllowFrom = @("LocalSubnet")
)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$config = Get-Content (Join-Path $repo "config\models.json") -Raw | ConvertFrom-Json
$svc = $config.services

function Listening([int]$p) { [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) }

function Ensure([string]$name, [int]$port, [string]$exe, [string[]]$argv, [string]$workdir, [int]$wait = 120) {
  if (Listening $port) { "{0,-12} up (port {1} already in use)" -f $name, $port; return }
  $params = @{ FilePath = $exe; WindowStyle = "Hidden"; ArgumentList = $argv; PassThru = $true
               RedirectStandardOutput = (Join-Path $logs "$name.out.log")
               RedirectStandardError = (Join-Path $logs "$name.err.log") }
  if ($workdir) { $params.WorkingDirectory = $workdir }
  try { $proc = Start-Process @params } catch { "{0,-12} ERROR {1}" -f $name, $_.Exception.Message; return }
  for ($i = 0; $i -lt $wait; $i++) {
    if (Listening $port) { "{0,-12} up (pid {1})" -f $name, $proc.Id; return }
    if ($proc.HasExited) { "{0,-12} FAILED (exit {1}) see {2}" -f $name, $proc.ExitCode, $params.RedirectStandardError; return }
    Start-Sleep 1
  }
  "{0,-12} TIMEOUT waiting for port {1}" -f $name, $port
}

$venv = Join-Path $Root "services\gateway-venv\Scripts\python.exe"
$model = { param($rel) Join-Path $Root $rel }

$emb = $svc.embeddings
Ensure "embeddings" $emb.port (Join-Path $Root "bin\llama-vulkan\llama-server.exe") @(
  "-m", (& $model $emb.model), "-ngl", "99", "--host", "127.0.0.1", "--port", "$($emb.port)",
  "-c", "$($emb.ctx)", "--embedding", "--pooling", "mean") ""

Ensure "rerank" $svc.rerank.port $venv @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$($svc.rerank.port)") (Join-Path $repo "services\rerank")
Ensure "asr" $svc.asr.port $venv @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$($svc.asr.port)") (Join-Path $repo "services\asr")

$breeze = $svc."tts-breeze"
Ensure "tts-breeze" $breeze.port (Join-Path $Root "bin\breeze-tts\breeze-server.exe") @(
  (& $model $breeze.model), "--host", "127.0.0.1", "--port", "$($breeze.port)",
  "--voices-dir", (Join-Path $Root "models\tts\voices")) ""

Ensure "tts-voxcpm" $svc."tts-voxcpm".port $venv @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$($svc.'tts-voxcpm'.port)") (Join-Path $repo "services\voxcpm") 180
Ensure "video" $svc.video.port $venv @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$($svc.video.port)") (Join-Path $repo "services\video") 60

Ensure "gateway" $Port $venv @("-m", "uvicorn", "gateway.main:app", "--host", $Bind, "--port", "$Port") $repo 60

if (-not (Get-NetFirewallRule -Name LocalInferenceGateway -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name LocalInferenceGateway -DisplayName "local-inference gateway" -Direction Inbound `
    -Protocol TCP -LocalPort $Port -Action Allow -RemoteAddress $AllowFrom | Out-Null
  "firewall     rule created for port $Port"
}
