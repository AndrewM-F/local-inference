# Downloads the native runtimes used by this stack into <root>/bin.
# Re-runnable: existing directories are left alone unless -Force is passed.
#
#   .\scripts\install-runtimes.ps1              # uses $env:INFERENCE_ROOT or C:\local-inference
#   .\scripts\install-runtimes.ps1 -Root D:\ai -Force
param(
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" }),
  [switch]$Force
)
$ErrorActionPreference = "Continue"
$bin = Join-Path $Root "bin"
$cache = Join-Path $Root "cache"
New-Item -ItemType Directory -Force -Path $bin, $cache, (Join-Path $Root "logs") | Out-Null

function Fetch([string]$url, [string]$dest) {
  if ((Test-Path $dest) -and -not $Force) { "skip $(Split-Path -Leaf $dest)"; return $true }
  & curl.exe -L --http1.1 -A "Mozilla/5.0" --fail -sS --retry 3 --retry-delay 5 -o $dest $url
  if ($LASTEXITCODE -ne 0) { "FAILED $(Split-Path -Leaf $dest)"; return $false }
  "ok   $(Split-Path -Leaf $dest)"
}

function Unpack([string]$archive, [string]$dest, [switch]$TarGz) {
  if ((Test-Path $dest) -and -not $Force) { return }
  if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  if ($TarGz) { & tar.exe -xzf $archive -C $dest } else { Expand-Archive -Path $archive -DestinationPath $dest -Force }
  # flatten the single wrapper directory most archives ship with
  $inner = Get-ChildItem $dest -Directory -ErrorAction SilentlyContinue
  if ($inner.Count -eq 1 -and -not (Get-ChildItem $dest -File -ErrorAction SilentlyContinue)) {
    Get-ChildItem $inner[0].FullName -Force | Move-Item -Destination $dest -Force
    Remove-Item $inner[0].FullName -Recurse -Force
  }
}

"=== llama.cpp (Vulkan + SYCL builds) ==="
$release = (Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")
foreach ($variant in "vulkan", "sycl") {
  $asset = $release.assets | Where-Object { $_.name -like "*bin-win-$variant-x64.zip" } | Select-Object -First 1
  if (-not $asset) { "no $variant asset in $($release.tag_name)"; continue }
  $zip = Join-Path $cache $asset.name
  if (Fetch $asset.browser_download_url $zip) { Unpack $zip (Join-Path $bin "llama-$variant") }
}

"=== stable-diffusion.cpp (Vulkan) ==="
$sd = (Invoke-RestMethod "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest")
$sdAsset = $sd.assets | Where-Object { $_.name -like "*bin-win-vulkan-x64.zip" } | Select-Object -First 1
if ($sdAsset -and (Fetch $sdAsset.browser_download_url (Join-Path $cache $sdAsset.name))) {
  Unpack (Join-Path $cache $sdAsset.name) (Join-Path $bin "sd")
}

"=== transcribe.cpp (Vulkan, ships a DLL) ==="
$tr = (Invoke-RestMethod "https://api.github.com/repos/handy-computer/transcribe.cpp/releases/latest")
$trAsset = $tr.assets | Where-Object { $_.name -like "*windows*cpu-vulkan*.tar.gz" } | Select-Object -First 1
if ($trAsset -and (Fetch $trAsset.browser_download_url (Join-Path $cache $trAsset.name))) {
  Unpack (Join-Path $cache $trAsset.name) (Join-Path $bin "transcribe") -TarGz
}

"=== Breeze-TTS-2.cpp (Vulkan) ==="
$bz = (Invoke-RestMethod "https://api.github.com/repos/HoppouAI/Breeze-TTS-2.cpp/releases/latest")
$bzAsset = $bz.assets | Where-Object { $_.name -like "*windows-x64-vulkan.zip" } | Select-Object -First 1
if ($bzAsset -and (Fetch $bzAsset.browser_download_url (Join-Path $cache $bzAsset.name))) {
  Unpack (Join-Path $cache $bzAsset.name) (Join-Path $bin "breeze-tts")
}

"=== Python services (gateway, voxcpm, rerank) ==="
foreach ($venv in "gateway-venv", "voxcpm-venv") {
  $path = Join-Path $Root "services\$venv"
  if (-not (Test-Path "$path\Scripts\python.exe")) { & py -3.12 -m venv $path }
}
& (Join-Path $Root "services\gateway-venv\Scripts\python.exe") -m pip install --quiet --disable-pip-version-check fastapi uvicorn
"runtime install complete under $Root"
