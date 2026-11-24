# Downloads the model files this stack expects into <root>/models.
# Files are public; gated repositories need HF_TOKEN in config/inference.env.
#
#   .\scripts\provision-models.ps1
#   .\scripts\provision-models.ps1 -Root D:\ai -Only embeddings,asr
param(
  [string]$Root = $(if ($env:INFERENCE_ROOT) { $env:INFERENCE_ROOT } else { "C:\local-inference" }),
  [string[]]$Only = @()
)
$ErrorActionPreference = "Continue"
$HF = "https://huggingface.co"
$models = Join-Path $Root "models"
New-Item -ItemType Directory -Force -Path $models | Out-Null

# name = <destination relative path>; repo/file = Hugging Face source
$files = @(
  @{ name = "embeddings"; path = "embeddinggemma-2-Q8_0.gguf";            url = "$HF/ggml-org/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-Q8_0.gguf" },
  @{ name = "rerank";     path = "ettin-reranker-400m-v1/openvino/openvino_model.xml"; url = "$HF/cross-encoder/ettin-reranker-400m-v1/resolve/main/openvino/openvino_model.xml" },
  @{ name = "rerank";     path = "ettin-reranker-400m-v1/openvino/openvino_model.bin"; url = "$HF/cross-encoder/ettin-reranker-400m-v1/resolve/main/openvino/openvino_model.bin" },
  @{ name = "asr";        path = "parakeet-unified-en-0.6b-Q8_0.gguf";    url = "$HF/handy-computer/parakeet-unified-en-0.6b-gguf/resolve/main/parakeet-unified-en-0.6b-Q8_0.gguf" },
  @{ name = "tts-breeze"; path = "breeze-tts-2-q8_0.gguf";                url = "$HF/HoppouAI/Breeze-TTS-2.cpp/resolve/main/breeze-tts-2-q8_0.gguf" },
  @{ name = "tts-voxcpm"; path = "voxcpm2-q8_0-locdit-f16.gguf";          url = "$HF/cstr/voxcpm2-GGUF/resolve/main/voxcpm2-q8_0-locdit-f16.gguf" },
  @{ name = "video";      path = "minimax_h3_fl2va_pruned-Q4_K.gguf";     url = "$HF/unsloth/MiniMax-H3-GGUF/resolve/main/minimax_h3_fl2va_pruned-Q4_K.gguf" },
  @{ name = "video";      path = "minimax/qwen3vl_32b_minimax_h3-Q2_K_M.gguf"; url = "$HF/unsloth/MiniMax-H3-GGUF/resolve/main/qwen3vl_32b_minimax_h3-Q2_K_M.gguf" },
  @{ name = "video";      path = "minimax/minimax_h3_video_vae_int8.safetensors"; url = "$HF/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_int8_convrot.safetensors" },
  @{ name = "video";      path = "minimax/minimax_h3_audio_vae_fp32.safetensors"; url = "$HF/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors" }
)

function Download([string]$url, [string]$dest) {
  $dir = Split-Path -Parent $dest
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  if ((Test-Path $dest) -and (Get-Item $dest).Length -gt 1000) { "skip $(Split-Path -Leaf $dest)"; return }
  # The CDN drops long transfers; resume with stall detection until the file stops growing.
  for ($attempt = 1; $attempt -le 30; $attempt++) {
    $have = if (Test-Path $dest) { (Get-Item $dest).Length } else { 0 }
    $args = @("-L", "--http1.1", "-A", "Mozilla/5.0", "--fail", "-sS", "-o", $dest,
              "--speed-limit", "51200", "--speed-time", "30")
    if ($have -gt 0) { $args += @("-C", "-") }
    if ($env:HF_TOKEN) { $args += @("-H", "Authorization: Bearer $($env:HF_TOKEN)") }
    & curl.exe @args $url
    if ($LASTEXITCODE -eq 0) { "ok   $(Split-Path -Leaf $dest)"; return }
    Start-Sleep 2
  }
  "FAILED $(Split-Path -Leaf $dest)"
}

foreach ($f in $files) {
  if ($Only.Count -gt 0 -and $Only -notcontains $f.name) { continue }
  Download $f.url (Join-Path $models $f.path)
}
"models provisioned under $models"
