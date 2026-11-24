# Architecture

## Shape

One gateway process exposes a single authenticated HTTP surface; each model runs in
its own process behind it. That keeps failure isolated (a crashed TTS server cannot
take the API down), lets every service pick the runtime that is actually fastest
for its workload, and makes VRAM budgeting explicit.

```
client ──bearer──> gateway (FastAPI)
                     ├── embeddings   :8081  llama.cpp, Vulkan
                     ├── rerank       :8082  OpenVINO, GPU
                     ├── asr          :8083  CrispASR, Vulkan
                     ├── tts-breeze   :8084  Breeze-TTS-2.cpp, Vulkan
                     ├── tts-voxcpm   :8086  CrispASR, Vulkan
                     ├── classifier          hosted (TypeSafe)
                     └── video        :8090  stable-diffusion.cpp, on demand
```

## Resident vs on demand

The small models total roughly 6-8 GB of VRAM and stay up so latency is low.
Video is the exception: its denoiser plus int8 VAE peak near 14 GiB, and its text
encoder is larger than the remaining VRAM, so a video job cannot share the card.
`services/video` therefore stops the resident services (via a configurable hook),
renders, and triggers a restore task. This is why the gateway treats video as a
job rather than a proxy.

## Runtime selection

Selection is driven by measurement, not preference:

- **llama.cpp** for GGUF text models. Two builds are installed (`llama-vulkan`,
  `llama-sycl`) so a workload can be benchmarked against both.
- **OpenVINO** for ModernBERT cross-encoders: llama.cpp cannot load them, and the
  model repositories ship OpenVINO IR.
- **CrispASR** for Parakeet-family ASR and VoxCPM2 TTS: it consumes the GGUFs those
  projects publish.
- **Breeze-TTS-2.cpp** for Breeze-TTS-2: its GGUF is not loadable by CrispASR, and
  vice versa.
- **stable-diffusion.cpp** for the video model: the GGUF is tagged for it.

## Portability notes

- Paths are relative to `INFERENCE_ROOT`; nothing is absolute in version control.
- The gateway reads `config/inference.env` but real environment variables win.
- Scripts are PowerShell because the reference deployment is Windows; the Python
  services and `clients/infer.py` are platform-neutral.
- A boot-triggered S4U scheduled task starts the stack without an interactive
  session. That matters on Windows: an "at logon" task never runs on a headless
  box, and the GPU is still visible from session 0.

## Known limits

- The shell-executor pattern used for CI on the same machine has no cgroups:
  jobs can consume the whole box. Give CI a lower process priority and cap its
  build directory.
- Windows Sandbox / nested VMs are not a fidelity strategy for this kind of
  testing: they have no GPU and are ephemeral.
- Consumer Windows cannot run Linux containers without a nested VM, and Windows
  containers need a server-grade setup; neither belongs in this stack.
