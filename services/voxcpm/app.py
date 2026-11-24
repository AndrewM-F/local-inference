"""VoxCPM2 TTS service (CrispASR ggml/Vulkan backend).

    POST /v1/audio/speech {"input": "...", "steps": 4}
    GET  /health

Environment (all optional):
    INFERENCE_ROOT      root holding models/
    VOXCPM_MODEL        GGUF (default models/voxcpm2-q8_0-locdit-f16.gguf)
    VOXCPM_REF_AUDIO    reference clip for cloning (default models/tts/reference.wav)
    VOXCPM_REF_TEXT     exact transcript of that clip
    VOXCPM_STEPS        CFM steps (default 4; 10 is slower, 2 degenerates)

The reference clip is required: VoxCPM2 clones a voice, it has no built-in one.
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
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

ROOT = pathlib.Path(os.environ.get("INFERENCE_ROOT", pathlib.Path(__file__).resolve().parents[2]))
MODEL = pathlib.Path(os.environ.get("VOXCPM_MODEL", ROOT / "models" / "voxcpm2-q8_0-locdit-f16.gguf"))
REF_AUDIO = pathlib.Path(os.environ.get("VOXCPM_REF_AUDIO", ROOT / "models" / "tts" / "reference.wav"))
REF_TEXT = os.environ.get("VOXCPM_REF_TEXT", "")
STEPS = int(os.environ.get("VOXCPM_STEPS", "4"))

app = FastAPI(title="local-inference-voxcpm")
_lock = threading.Lock()
_state: dict[str, object] = {}


@app.on_event("startup")
def load() -> None:
    t0 = time.time()
    session = c.Session(str(MODEL), backend="voxcpm2-tts", n_threads=4)
    session.accept_marking_responsibility()
    if REF_TEXT:
        session.set_voice(str(REF_AUDIO), REF_TEXT)
    session.set_tts_steps(STEPS)
    rate = session.output_sample_rate
    _state.update(session=session, rate=int(rate() if callable(rate) else (rate or 48000)),
                  load_s=round(time.time() - t0, 2))


@app.get("/health")
def health() -> dict:
    if "session" not in _state:
        raise HTTPException(503, "model not loaded")
    return {"status": "ok", "model": MODEL.name, "sample_rate": _state["rate"],
            "steps": STEPS, "load_s": _state["load_s"]}


@app.post("/v1/audio/speech")
def speech(payload: dict) -> Response:
    text = payload.get("input") or payload.get("text")
    if not text:
        raise HTTPException(422, "missing 'input'")
    if "session" not in _state:
        raise HTTPException(503, "model not loaded")
    steps = int(payload.get("steps") or STEPS)
    t0 = time.time()
    with _lock:
        session = _state["session"]
        session.set_tts_steps(steps)
        pcm = np.asarray(session.synthesize(text), dtype=np.float32).reshape(-1)
    seconds = time.time() - t0
    if not len(pcm):
        raise HTTPException(500, "synthesize returned no audio")
    rate = int(_state["rate"])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    audio_s = len(pcm) / rate
    return Response(content=buf.getvalue(), media_type="audio/wav",
                    headers={"x-audio-seconds": f"{audio_s:.2f}",
                             "x-gen-seconds": f"{seconds:.2f}",
                             "x-rtf": f"{audio_s / seconds:.2f}" if seconds else "0"})
