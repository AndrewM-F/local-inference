"""Cross-encoder reranker service.

Some rerankers (ModernBERT-family, e.g. Ettin) do not load in llama.cpp, so this
runs the model's prebuilt OpenVINO IR on the GPU and replays the
sentence-transformers head stack in numpy.

    POST /rerank {"query": "...", "documents": ["...", "..."]}
      -> {"results": [{"index": 0, "relevance_score": 4.12}, ...], "took_ms": 84.2}
    GET  /health

Environment:
    INFERENCE_ROOT      root holding models/
    RERANK_MODEL_DIR    directory with openvino/openvino_model.xml + tokenizer
                        (default models/ettin-reranker-400m-v1)
    RERANK_OPENVINO_DEVICE  GPU, GPU.1, CPU (default GPU)
    RERANK_MAX_LENGTH   tokens per pair (default 512)
"""

from __future__ import annotations

import json
import os
import pathlib
import time

import numpy as np
import openvino as ov
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from tokenizers import Tokenizer

ROOT = pathlib.Path(os.environ.get("INFERENCE_ROOT", pathlib.Path(__file__).resolve().parents[2]))
MODEL_DIR = pathlib.Path(os.environ.get("RERANK_MODEL_DIR", ROOT / "models" / "ettin-reranker-400m-v1"))
DEVICE = os.environ.get("RERANK_OPENVINO_DEVICE", "GPU")
MAX_LEN = int(os.environ.get("RERANK_MAX_LENGTH", "512"))

app = FastAPI(title="local-inference-rerank")
_state: dict[str, object] = {}


def _dense(path: pathlib.Path, x: np.ndarray) -> np.ndarray:
    """Apply a sentence-transformers Dense module (config.json + safetensors)."""
    from safetensors.numpy import load_file

    cfg = json.loads((path / "config.json").read_text())
    weights = load_file(str(path / "model.safetensors"))
    w = weights.get("linear.weight") if "linear.weight" in weights else weights[list(weights)[0]]
    b = weights.get("linear.bias")
    y = x @ np.asarray(w).T + (np.asarray(b) if b is not None else 0.0)
    if cfg.get("activation_function") == "gelu":
        y = 0.5 * y * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (y + 0.044715 * y**3)))
    return y


def _layer_norm(path: pathlib.Path, x: np.ndarray) -> np.ndarray:
    from safetensors.numpy import load_file

    weights = load_file(str(path / "model.safetensors"))
    eps = 1e-5
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    out = (x - mean) / np.sqrt(var + eps)
    for key in ("weight", "bias"):
        if key in weights:
            out = out * weights[key] if key == "weight" else out + weights[key]
    return out


@app.on_event("startup")
def load() -> None:
    t0 = time.time()
    core = ov.Core()
    model = core.read_model(str(MODEL_DIR / "openvino" / "openvino_model.xml"))
    compiled = core.compile_model(model, DEVICE, {"INFERENCE_PRECISION_HINT": "f16"})
    tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_LEN)
    tokenizer.enable_padding()
    _state.update(compiled=compiled, tokenizer=tokenizer,
                  device=core.get_property(DEVICE, "FULL_DEVICE_NAME"), load_s=round(time.time() - t0, 2))


def _score(query: str, doc: str) -> float:
    enc = _state["tokenizer"].encode(query, doc)
    ids = np.array([enc.ids], dtype=np.int64)
    mask = np.array([enc.attention_mask], dtype=np.int64)
    out = _state["compiled"]({"input_ids": ids, "attention_mask": mask})
    logits = np.asarray(out[list(out)[0]])[0]
    x = logits.reshape(1, -1).astype(np.float32)
    for name in ("2_Dense", "3_LayerNorm", "4_Dense"):
        path = MODEL_DIR / name
        if not path.is_dir():
            continue
        x = _layer_norm(path, x) if "LayerNorm" in name else _dense(path, x)
    return float(x.reshape(-1)[0])


@app.get("/health")
def health() -> dict:
    if "compiled" not in _state:
        raise HTTPException(503, "model not loaded")
    return {"status": "ok", "device": _state["device"], "model_dir": MODEL_DIR.name,
            "max_length": MAX_LEN, "load_s": _state["load_s"]}


@app.post("/rerank")
def rerank(payload: dict) -> JSONResponse:
    query = payload.get("query")
    documents = payload.get("documents") or []
    if not query or not documents:
        raise HTTPException(422, "need 'query' and non-empty 'documents'")
    t0 = time.time()
    results = [{"index": i, "relevance_score": _score(query, d)} for i, d in enumerate(documents)]
    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return JSONResponse({"results": results, "took_ms": round((time.time() - t0) * 1000, 1)})
