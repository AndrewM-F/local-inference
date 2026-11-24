#!/usr/bin/env python3
"""infer - one client for a local-inference gateway.

    infer health
    infer models
    infer embed "text" ["text2" ...]
    infer rerank "query" "doc1" "doc2" ...
    infer asr recording.wav
    infer tts "hello" [--out out.wav] [--model breeze|voxcpm] [--voice NAME]
    infer video '{"prompt": "..."}'
    infer classify '{"state": "...", "questions": [...]}'

Environment
    INFER_HOST      host:port of the gateway (default 127.0.0.1:8080)
    GATEWAY_KEY     bearer token
    GATEWAY_KEY_FILE  file holding the token
                    (default <secrets-dir>/gateway.key)
"""

from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

HOST = os.environ.get("INFER_HOST") or (
    f"{os.environ.get('INFERENCE_HOST', '127.0.0.1')}:{os.environ.get('INFERENCE_PORT', '8080')}"
)
BASE = f"http://{HOST}"


def key() -> str:
    k = os.environ.get("GATEWAY_KEY", "").strip()
    if k:
        return k
    explicit = os.environ.get("GATEWAY_KEY_FILE")
    path = pathlib.Path(explicit).expanduser() if explicit else pathlib.Path.home() / ".config" / "inference-secrets" / "gateway.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    sys.exit(f"no gateway key: set GATEWAY_KEY, GATEWAY_KEY_FILE, or write {path}")


def call(path: str, payload: dict | None = None, raw: tuple[bytes, str] | None = None, timeout: int = 900) -> bytes:
    headers = {"Authorization": f"Bearer {key()}"}
    data = None
    if raw is not None:
        data, ctype = raw
        headers["Content-Type"] = ctype
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read(400).decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach {BASE}: {e.reason}")


def multipart(path: str, field: str = "file", extra: dict[str, str] | None = None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    fname = pathlib.Path(path).name
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n")
    parts.append(head.encode() + pathlib.Path(path).read_bytes() + b"\r\n")
    for k, v in (extra or {}).items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        sys.exit(2)
    cmd, args = argv[0], argv[1:]
    flags = {a.split("=")[0].lstrip("-"): a.split("=", 1)[1] for a in args if a.startswith("--") and "=" in a}
    args = [a for a in args if not a.startswith("--")]

    if cmd == "health":
        print(call("/health").decode())
    elif cmd == "models":
        print(json.dumps(json.loads(call("/v1/models")), indent=2))
    elif cmd == "embed":
        body = json.loads(call("/v1/embeddings", {"input": args}))
        for i, d in enumerate(body["data"]):
            print(f"{i}: dim={len(d['embedding'])}")
    elif cmd == "rerank":
        body = json.loads(call("/v1/rerank", {"query": args[0], "documents": args[1:]}))
        for r in body.get("results", []):
            print(f"{r.get('relevance_score', 0):.4f}  {args[1 + r['index']]}")
    elif cmd == "asr":
        data, ctype = multipart(args[0])
        print(call("/v1/audio/transcriptions", raw=(data, ctype)).decode())
    elif cmd == "tts":
        model = "voxcpm2" if flags.get("model") == "voxcpm" else "breeze-tts-2"
        payload = {"model": model, "input": args[0], "response_format": "wav"}
        if "voice" in flags:
            payload["voice"] = flags["voice"]
        out = pathlib.Path(flags.get("out", f"tts-{uuid.uuid4().hex[:6]}.wav"))
        out.write_bytes(call("/v1/audio/speech", payload))
        print(f"{out} ({out.stat().st_size} bytes)")
    elif cmd in ("video", "classify"):
        print(call(f"/v1/{cmd}", json.loads(args[0])).decode())
    else:
        sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
