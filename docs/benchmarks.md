# Benchmarks

Reference hardware: 8 vCPU, 32 GB RAM, one 16 GB Intel Arc-class GPU on Windows 11,
Vulkan driver, no CUDA. Numbers are from `llama-bench` and the services' own timing
output, three repetitions unless noted.

## llama.cpp backends, embedding model (Q8_0, 0.3B)

| Backend | prefill pp512 (t/s) | decode tg128 (t/s) |
|---|---|---|
| Vulkan | **31,060** | 182 |
| SYCL | 16,952 | **278** |

Vulkan wins prefill by ~1.8x, SYCL wins decode by ~1.5x. Embeddings and reranking
are prefill-only, so they run on Vulkan; anything that generates tokens belongs on
SYCL.

## Service latencies (warm, gateway included)

| Workload | Measurement |
|---|---|
| embed single string (768 dims) | 26-67 ms |
| rerank 3 documents (400M cross-encoder, OpenVINO GPU) | 87 ms |
| ASR, 6 s clip, Parakeet 0.6B Q8 | 0.2-0.3 s (RTF ~30) |
| TTS Breeze, ~2 s of speech | ~14 s on GPU, ~10 s on CPU |
| TTS VoxCPM2, 3.8 s of speech | 6.5 s at 10 steps, 4.8 s at 4 steps |

The Breeze vocoder is the outlier that justifies a CPU exception: 54 ms/frame on
CPU versus 258 ms/frame on Vulkan, against 3.7 ms/frame on a desktop NVIDIA card -
the GPU path for that one model is poorly served by the driver.

VoxCPM2 sampling steps: 10 steps gives RTF 0.59, 4 steps 0.77, 2 steps degenerates
into runaway audio. The default is 4.

## Video (MiniMax-H3 Q4_K, text encoder on CPU)

| Clip | Wall | Peak VRAM |
|---|---|---|
| 384x256, 9 frames, 2 steps | 38 s (models cached) | - |
| 640x384, 25 frames, 4 steps | 100 s (models cached) | 14.0 GiB |
| same 384x256 job, cold page cache | 448 s | - |

The gap between warm and cold is the whole story for video: the text encoder and
denoiser together exceed RAM, so a cold run re-reads tens of gigabytes. Unless the
box has enough RAM to keep both, budget minutes rather than seconds for the first
job after a reboot.

## ASR accuracy (smoke check, synthetic speech)

Four sentences, two synthetic voices, 50 words: corpus WER 10%. Two sentences were
perfect; the errors were a formatting difference ("three thirty" -> "3.30") and one
real mishearing. Synthetic speech is out of domain for a model trained on real
audio, so treat this as a smoke check, not a quality figure.
