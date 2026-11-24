"""local-inference gateway.

One authenticated HTTP surface in front of the model services on a machine.
Everything machine-specific comes from the environment (config/inference.env) and
config/models.json; nothing here hardcodes a host, port or path.

    python -m uvicorn gateway.main:app --host $INFERENCE_BIND --port $INFERENCE_PORT

Routes
    GET  /health                     per-service readiness
    GET  /v1/models                  catalogue with live state
    POST /v1/embeddings              llama.cpp (OpenAI shape)
    POST /v1/rerank                  OpenVINO cross-encoder
    POST /v1/audio/transcriptions    multipart or raw audio
    POST /v1/audio/speech            TTS (breeze or voxcpm)
    POST /v1/classify                TypeSafe "System One" decision model
    POST /v1/video                   on-demand video job
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFIG_FILE = pathlib.Path(os.environ.get("INFERENCE_CONFIG", REPO / "config" / "models.json"))


def load_env_file(path: pathlib.Path) -> None:
    """Minimal KEY=VALUE loader; real environment variables always win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file(pathlib.Path(os.environ.get("INFERENCE_ENV_FILE", REPO / "config" / "inference.env")))

ROOT = pathlib.Path(os.environ.get("INFERENCE_ROOT", REPO)).expanduser()
PORT = int(os.environ.get("INFERENCE_PORT", "8080"))


def secrets_dir() -> pathlib.Path:
    explicit = os.environ.get("GATEWAY_KEY_FILE")
    if explicit:
        return pathlib.Path(explicit).expanduser().parent
    return pathlib.Path.home() / ".config" / "inference-secrets"


def gateway_key() -> str:
    explicit = os.environ.get("GATEWAY_KEY_FILE")
    path = pathlib.Path(explicit).expanduser() if explicit else secrets_dir() / "gateway.key"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def service(name: str) -> dict[str, Any]:
    try:
        return load_config()["services"][name]
    except KeyError:
        raise HTTPException(404, f"unknown service {name}")


def model_path(svc: dict[str, Any]) -> pathlib.Path:
    return ROOT / svc["model"]


app = FastAPI(title="local-inference", version="1.0.0")


def require_key(authorization: str | None = Header(default=None)) -> None:
    expected = gateway_key()
    if not expected:
        raise HTTPException(503, "gateway key not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "missing or invalid bearer token")


# --------------------------------------------------------------------- state
class Managed:
    """Child process started on demand and stopped when idle."""

    def __init__(self, name: str, argv: list[str], port: int, idle_seconds: int = 0):
        self.name, self.argv, self.port = name, argv, port
        self.idle_seconds = idle_seconds
        self.proc = None
        self.last_used = 0.0
        self.lock = threading.Lock()

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2):
                return True
        except Exception:
            return False

    def ensure(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None and self.healthy():
                self.last_used = time.time()
                return
            log = ROOT / "logs" / f"{self.name}.gateway.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            self.proc = __import__("subprocess").Popen(
                self.argv, stdout=open(log, "ab"), stderr=__import__("subprocess").STDOUT,
                creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0),
            )
            deadline = time.time() + 180
            while time.time() < deadline:
                if self.healthy():
                    self.last_used = time.time()
                    return
                if self.proc.poll() is not None:
                    raise HTTPException(502, f"{self.name} exited during startup, see {log}")
                time.sleep(1)
            raise HTTPException(504, f"{self.name} did not become healthy")

    def reap(self) -> None:
        if self.idle_seconds and self.proc and time.time() - self.last_used > self.idle_seconds:
            self.proc.terminate()
            self.proc = None


REGISTRY: dict[str, Managed] = {}


# --------------------------------------------------------------------- proxy
def proxy(port: int, path: str, payload: dict, timeout: int = 900) -> JSONResponse:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return JSONResponse(json.load(r), status_code=r.status)
    except urllib.error.HTTPError as e:
        return Response(content=e.read(), status_code=e.code, media_type="application/json")
    except urllib.error.URLError as e:
        raise HTTPException(502, f"backend on port {port} unreachable: {e.reason}")


def proxy_raw(port: int, path: str, body: bytes, content_type: str, timeout: int = 900) -> Response:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                 headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(content=r.read(), media_type=r.headers.get("Content-Type"))
    except urllib.error.HTTPError as e:
        return Response(content=e.read(), status_code=e.code, media_type="application/json")
    except urllib.error.URLError as e:
        raise HTTPException(502, f"backend on port {port} unreachable: {e.reason}")


def is_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
            return True
    except Exception:
        return False


# --------------------------------------------------------------------- routes
@app.get("/health")
def health() -> dict[str, Any]:
    out = {}
    for name, cfg in load_config()["services"].items():
        out[name] = "hosted" if cfg.get("hosted") else ("up" if is_up(cfg["port"]) else "down")
    return {"gateway": "ok", "services": out}


@app.get("/v1/models", dependencies=[Depends(require_key)])
def models() -> dict[str, Any]:
    data = []
    for name, cfg in load_config()["services"].items():
        state = "hosted" if cfg.get("hosted") else ("up" if is_up(cfg["port"]) else "down")
        data.append({"id": name, "role": cfg.get("role"), "model": pathlib.Path(cfg.get("model", "")).name,
                     "source": cfg.get("source"), "resident": bool(cfg.get("resident")), "state": state})
    return {"object": "list", "data": data}


@app.post("/v1/embeddings", dependencies=[Depends(require_key)])
def embeddings(payload: dict) -> JSONResponse:
    return proxy(service("embeddings")["port"], "/v1/embeddings", payload)


@app.post("/v1/rerank", dependencies=[Depends(require_key)])
def rerank(payload: dict) -> JSONResponse:
    return proxy(service("rerank")["port"], "/rerank", payload)


@app.post("/v1/audio/transcriptions", dependencies=[Depends(require_key)])
async def transcribe(request: Request) -> Response:
    body = await request.body()
    return proxy_raw(service("asr")["port"], "/v1/audio/transcriptions", body,
                     request.headers.get("content-type", "application/octet-stream"))


@app.post("/v1/audio/speech", dependencies=[Depends(require_key)])
def speech(payload: dict) -> Response:
    name = "tts-breeze" if "breeze" in payload.get("model", "breeze") else "tts-voxcpm"
    cfg = service(name)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{cfg['port']}/v1/audio/speech", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return Response(content=r.read(), media_type=r.headers.get("Content-Type", "audio/wav"))
    except urllib.error.HTTPError as e:
        return Response(content=e.read(), status_code=e.code, media_type="application/json")
    except urllib.error.URLError as e:
        raise HTTPException(502, f"backend on port {cfg['port']} unreachable: {e.reason}")


@app.post("/v1/classify", dependencies=[Depends(require_key)])
def classify(payload: dict) -> JSONResponse:
    from gateway.typesafe import DEFAULT_MODEL, classify as typesafe_classify

    try:
        return JSONResponse(typesafe_classify(payload["state"], payload["questions"],
                                             payload.get("model", DEFAULT_MODEL)))
    except KeyError as e:
        raise HTTPException(422, f"missing field {e}")
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.post("/v1/video", dependencies=[Depends(require_key)])
def video(payload: dict) -> JSONResponse:
    """Job service: frees VRAM, renders, restores the resident stack."""
    return proxy(service("video")["port"], "/v1/video", payload, timeout=3600)


@app.post("/admin/reap")
def reap() -> dict[str, str]:
    for name, svc in REGISTRY.items():
        svc.reap()
    return {n: ("running" if s.proc and s.proc.poll() is None else "stopped") for n, s in REGISTRY.items()}
