"""On-demand video generation (image/text to video via stable-diffusion.cpp).

Video is the one workload that cannot share the GPU: the denoiser plus the video
VAE peak around 14 GiB, and the text encoder is large enough that it has to run on
the CPU. So a job stops the resident services, renders, and asks the stack task to
bring them back.

    POST /v1/video {"prompt": "...", "width": 640, "height": 384,
                    "frames": 25, "steps": 4}
      -> {"file": "...webm", "seconds": 99.8}
    GET  /health

Environment (all optional, sensible defaults):
    INFERENCE_ROOT          root holding bin/ and models/
    SD_CLI                  path to sd-cli (default <root>/bin/sd/sd-cli.exe)
    VIDEO_DENOISER          denoiser GGUF (default models/minimax_h3_fl2va_pruned-Q4_K.gguf)
    VIDEO_TEXT_ENCODER      LLM text encoder GGUF (default models/minimax/qwen3vl_32b_minimax_h3-Q2_K_M.gguf)
    VIDEO_VAE               video VAE (default models/minimax/minimax_h3_video_vae_int8.safetensors)
    VIDEO_AUDIO_VAE         audio VAE (default models/minimax/minimax_h3_audio_vae_fp32.safetensors)
    VIDEO_OUTPUT_DIR        where clips are written (default <root>/bench/video)
    VIDEO_FREE_VRAM_HOOK    command that stops resident services before a job
    VIDEO_RESTORE_TASK      scheduled task that restores them afterwards
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

ROOT = pathlib.Path(os.environ.get("INFERENCE_ROOT", pathlib.Path(__file__).resolve().parents[2]))
SD = pathlib.Path(os.environ.get("SD_CLI", ROOT / "bin" / "sd" / "sd-cli.exe"))
DENOISER = pathlib.Path(os.environ.get("VIDEO_DENOISER", ROOT / "models" / "minimax_h3_fl2va_pruned-Q4_K.gguf"))
TEXT_ENCODER = pathlib.Path(os.environ.get("VIDEO_TEXT_ENCODER", ROOT / "models" / "minimax" / "qwen3vl_32b_minimax_h3-Q2_K_M.gguf"))
VIDEO_VAE = pathlib.Path(os.environ.get("VIDEO_VAE", ROOT / "models" / "minimax" / "minimax_h3_video_vae_int8.safetensors"))
AUDIO_VAE = pathlib.Path(os.environ.get("VIDEO_AUDIO_VAE", ROOT / "models" / "minimax" / "minimax_h3_audio_vae_fp32.safetensors"))
OUT = pathlib.Path(os.environ.get("VIDEO_OUTPUT_DIR", ROOT / "bench" / "video"))
FREE_VRAM_HOOK = os.environ.get("VIDEO_FREE_VRAM_HOOK", "")
RESTORE_TASK = os.environ.get("VIDEO_RESTORE_TASK", "")

app = FastAPI(title="local-inference-video")
_job = threading.Lock()
_state: dict[str, object] = {"busy": False, "last": None}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "busy": _state["busy"], "last": _state["last"],
            "model": DENOISER.name, "backend": "stable-diffusion.cpp (text encoder on cpu)"}


@app.post("/v1/video")
def video(payload: dict) -> JSONResponse:
    prompt = payload.get("prompt")
    if not prompt:
        raise HTTPException(422, "missing 'prompt'")
    if not _job.acquire(blocking=False):
        raise HTTPException(409, "a video job is already running")
    try:
        _state["busy"] = True
        if FREE_VRAM_HOOK:
            subprocess.run(FREE_VRAM_HOOK, shell=True, capture_output=True, timeout=600)
        OUT.mkdir(parents=True, exist_ok=True)
        out = OUT / f"{uuid.uuid4().hex[:8]}.webm"
        argv = [
            str(SD), "--mode", "vid_gen",
            "--diffusion-model", str(DENOISER),
            "--llm", str(TEXT_ENCODER),
            "--vae", str(VIDEO_VAE),
            "--audio-vae", str(AUDIO_VAE),
            "--prompt", prompt,
            "--width", str(int(payload.get("width", 640))),
            "--height", str(int(payload.get("height", 384))),
            "--video-frames", str(int(payload.get("frames", 25))),
            "--steps", str(int(payload.get("steps", 4))),
            "--cfg-scale", "1.0",
            "--backend", "te=cpu",
            "--flash-attn", "off,diffusion=on",
            "--vae-tiling",
            "--output", str(out),
        ]
        t0 = time.time()
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
        seconds = round(time.time() - t0, 1)
        _state["last"] = {"file": str(out), "seconds": seconds}
        if proc.returncode != 0 or not out.exists():
            raise HTTPException(500, (proc.stderr or proc.stdout)[-800:])
        return JSONResponse({"file": str(out), "seconds": seconds,
                             "width": payload.get("width", 640), "height": payload.get("height", 384),
                             "frames": payload.get("frames", 25), "steps": payload.get("steps", 4)})
    finally:
        _state["busy"] = False
        _job.release()
        if RESTORE_TASK:
            subprocess.Popen(["schtasks.exe", "/Run", "/TN", RESTORE_TASK],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
