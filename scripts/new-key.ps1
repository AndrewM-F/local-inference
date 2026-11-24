# Creates the gateway bearer token in the secrets directory (never in the repo).
#
#   .\scripts\new-key.ps1
param(
  [string]$SecretsDir = $(if ($env:GATEWAY_KEY_FILE) {
      Split-Path -Parent $env:GATEWAY_KEY_FILE
    } else { Join-Path $env:USERPROFILE ".config\inference-secrets" })
)
New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null
$file = Join-Path $SecretsDir "gateway.key"
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$key = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
Set-Content -Path $file -Value $key -NoNewline -Encoding ASCII
& icacls $file /inheritance:r /grant "$($env:USERNAME):(F)" /grant "SYSTEM:(F)" | Out-Null
"wrote $file (mode restricted). Read it with: Get-Content `"$file`""
