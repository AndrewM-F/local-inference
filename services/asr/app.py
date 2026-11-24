"""ASR service: Parakeet (or any CrispASR-supported ASR model) behind HTTP.

    POST /v1/audio/transcriptions   multipart (OpenAI shape) or raw audio body
    GET  /health

Environment:
    INFERENCE_ROOT   root holding models/
    ASR_MODEL        GGUF (default models/parakeet-unified-en-0.6b-Q8_0.gguf)
    ASR_BACKEND      CrispASR backend name (default parakeet)
    ASR_SAMPLE_RATE  resample target (default 16000)
"""

from __future__ import annotations

import io
import os
import pathlib
import threading
import time
import wave

import crispasr as c
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = pathlib.Path(os.environ.get("INFERENCE_ROOT", pathlib.Path(__file__).resolve().parents[2]))
MODEL = pathlib.Path(os.environ.get("ASR_MODEL", ROOT / "models" / "parakeet-unified-en-0.6b-Q8_0.gguf"))
BACKEND = os.environ.get("ASR_BACKEND", "parakeet")
RATE = int(os.environ.get("ASR_SAMPLE_RATE", "16000"))

app = FastAPI(title="local-inference-asr")
_lock = threading.Lock()
_state: dict[str, object] = {}


def _decode(data: bytes) -> np.ndarray:
    """Accept WAV in any rate/channel count; return mono float32 at RATE."""
    with wave.open(io.BytesIO(data), "rb") as w:
        frames = w.readframes(w.getnframes())
        channels, width, src = w.getnchannels(), w.getsampwidth(), w.getframerate()
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise HTTPException(415, "unsupported sample width")
    pcm = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    pcm /= float(np.iinfo(dtype).max)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if src != RATE:
        duration = len(pcm) / src
        count = int(duration * RATE)
        pcm = np.interp(np.linspace(0, len(pcm) - 1, count), np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


@app.on_event("startup")
def load() -> None:
    t0 = time.time()
    _state.update(session=c.Session(str(MODEL), backend=BACKEND), load_s=round(time.time() - t0, 2))


@app.get("/health")
def health() -> dict:
    if "session" not in _state:
        raise HTTPException(503, "model not loaded")
    return {"status": "ok", "model": MODEL.name, "backend": BACKEND,
            "sample_rate": RATE, "load_s": _state["load_s"]}


@app.post("/v1/audio/transcriptions")
async def transcribe(request: Request) -> JSONResponse:
    body = await request.body()
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        boundary = ctype.split("boundary=")[-1].encode()
        for part in body.split(b"--" + boundary):
            if b"filename=" in part and b"\r\n\r\n" in part:
                body = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                break
    try:
        pcm = _decode(body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"could not read audio: {e}")
    t0 = time.time()
    with _lock:
        segments = _state["session"].transcribe_pcm(pcm, sample_rate=RATE)
    wall = time.time() - t0
    text = " ".join(getattr(s, "text", "").strip() for s in segments).strip()
    audio_s = len(pcm) / RATE
    return JSONResponse({"text": text, "audio_s": round(audio_s, 3), "wall_s": round(wall, 3),
                         "rtf": round(audio_s / wall, 2) if wall else None})
