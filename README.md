# local-inference

A small, self-hosted inference box: one authenticated HTTP API in front of local
models for **embeddings, reranking, speech-to-text, text-to-speech, video and
typed classification**, with per-service VRAM/RAM budgets and an on-demand
lifecycle for the models that cannot stay resident.

Built and measured on Windows 11 with an Intel Arc GPU (Vulkan + SYCL, no CUDA),
but the runtimes are portable: llama.cpp, stable-diffusion.cpp, Breeze-TTS-2.cpp
and CrispASR all run on Vulkan, and the gateway is plain Python.

## What it serves

| Route | Model class | Runtime |
|---|---|---|
| `POST /v1/embeddings` | embedding model (Gemma-class) | llama.cpp (Vulkan) |
| `POST /v1/rerank` | cross-encoder reranker (400M) | OpenVINO on the GPU |
| `POST /v1/audio/transcriptions` | Parakeet 0.6B | CrispASR / transcribe.cpp |
| `POST /v1/audio/speech` | Breeze-TTS-2, VoxCPM2 | Breeze-TTS-2.cpp, CrispASR |
| `POST /v1/classify` | TypeSafe "System One" (Jev) | hosted API |
| `POST /v1/video` | MiniMax-H3 Q4_K | stable-diffusion.cpp |
| `GET /health`, `GET /v1/models` | service state | gateway |

Everything is bearer-authenticated; the token lives outside the repository.

## Requirements

- Windows 11 with a Vulkan-capable GPU (16 GB VRAM is enough for everything
  except simultaneous video + resident models), or Linux with the same runtimes.
- Python 3.12, PowerShell 7 or 5.1, ~60 GB of disk for the full model set.
- Optional: a Tailscale/LAN network if other machines should reach the gateway.

## Quick start

```powershell
# 1. configuration: copy the example and edit it
Copy-Item config\inference.env.example config\inference.env
notepad config\inference.env          # set INFERENCE_ROOT (and GATEWAY_KEY_FILE if you like)

# 2. bearer token (written outside the repo)
.\scripts\new-key.ps1

# 3. native runtimes + the models listed in config/models.json
.\scripts\install-runtimes.ps1
.\scripts\provision-models.ps1

# 4. start everything, and register it at boot
.\scripts\start-stack.ps1
.\scripts\register-autostart.ps1
```

Then:

```bash
export INFER_HOST=127.0.0.1:8080
python clients/infer.py health
python clients/infer.py embed "the gateway is up"
python clients/infer.py rerank "capital of France" "Paris is the capital of France." "Bananas are yellow."
```

## Layout

```
config/     inference.env (yours, gitignored) + models.json (models, ports, budgets)
gateway/    FastAPI router: auth, /health, /v1/models, proxying, lifecycle
services/   the service implementations the gateway fronts (asr, rerank, tts, video)
clients/    infer.py - a dependency-free CLI for the API
scripts/    install, provision, start, autostart, bench, free-vram, key generation
docs/       architecture, configuration, benchmarks
```

## Things worth knowing before you copy this

These were paid for in debugging time:

- **Pair a GGUF with the runtime its repo names.** Community GGUFs are built for a
  specific engine: a CrispASR-flavoured Breeze GGUF fails in Breeze-TTS-2.cpp with
  `missing tensor: codec.enc.0.conv.bias`, and Breeze-TTS-2.cpp's own GGUF is
  rejected by CrispASR. Same-shaped files are not interchangeable.
- **ModernBERT rerankers do not run in llama.cpp.** They need the OpenVINO/ONNX
  export the model repo ships (`bert.context_length` is missing from converter
  GGUFs). `services/rerank` replays the sentence-transformers heads in numpy.
- **TTS models are voice-cloning, not fixed-voice.** Breeze-TTS-2 and VoxCPM2 both
  need a reference clip + its exact transcript (`VOXCPM_REF_*`); with no voice you
  get zero-length audio, not an error.
- **Measurement decides the backend, not brand loyalty.** On Arc, prefill-heavy
  work (embeddings, rerank) is ~1.8x faster on Vulkan than SYCL, while token
  generation is ~1.5x faster on SYCL; a TTS vocoder can be 4x faster on CPU than
  on the GPU. `scripts/bench-llama.ps1` exists to keep those choices honest.
- **Video needs exclusivity.** The denoiser + int8 VAE peak near 14 GiB, and the
  text encoder is large enough to force `te=cpu`. The job service therefore stops
  the resident stack, renders, and restores it.

See `docs/architecture.md` for the full rationale and `docs/benchmarks.md` for the
measured numbers behind the defaults.

## Licence

No licence has been chosen yet. Add one before redistributing or accepting
contributions.
