# Compares llama.cpp builds (Vulkan vs SYCL, etc.) on one GGUF so the backend
# choice is evidence-based: prefill-bound work wants prefill throughput,
# generation wants token throughput.
#
#   .\scripts\bench-llama.ps1 -Model C:\local-inference\models\embeddinggemma-2-Q8_0.gguf
param(
  [Parameter(Mandatory = $true)][string]$Model,
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" }),
  [int]$PromptTokens = 512,
  [int]$GenTokens = 128,
  [int]$Reps = 3,
  [string]$OutFile = ""
)
$rows = @()
foreach ($build in Get-ChildItem (Join-Path $Root "bin") -Directory -Filter "llama-*") {
  $bench = Join-Path $build.FullName "llama-bench.exe"
  if (-not (Test-Path $bench)) { continue }
  "== $($build.Name)"
  $raw = & $bench -m $Model -p $PromptTokens -n $GenTokens -r $Reps -o json 2>&1 | Out-String
  try { $parsed = $raw | ConvertFrom-Json } catch { "  could not parse output"; continue }
  foreach ($r in $parsed) {
    $rows += [pscustomobject]@{
      backend = $r.backend; build = $build.Name; model = $r.model_filename
      test = $(if ($r.n_prompt -gt 0) { "pp$($r.n_prompt)" } else { "tg$($r.n_gen)" })
      tps = [math]::Round($r.avg_ts, 2); stddev = [math]::Round($r.stddev_ts, 2)
    }
  }
}
$rows | Format-Table -AutoSize
if ($OutFile) { $rows | ConvertTo-Json -Depth 4 | Set-Content $OutFile -Encoding UTF8; "wrote $OutFile" }
