"""TypeSafe / Jev provider for the gateway's /v1/classify route.

Jev is a System One (decision) model: it takes a `state` plus typed `questions`
and returns calibrated probabilities, not chat completions.

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    GET  https://api.typesafe.ai/v1/models

Key resolution: $TYPESAFE_API_KEY, then <secrets-dir>/typesafe.key
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

BASE = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-latest"


def secrets_dir() -> pathlib.Path:
    explicit = os.environ.get("GATEWAY_KEY_FILE")
    if explicit:
        return pathlib.Path(explicit).expanduser().parent
    return pathlib.Path.home() / ".config" / "inference-secrets"


def api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    path = secrets_dir() / "typesafe.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    raise RuntimeError("no TypeSafe key: set TYPESAFE_API_KEY or write <secrets-dir>/typesafe.key")


def _request(method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "local-inference/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"typesafe {method} {path} -> {e.code}: {e.read(500).decode('utf-8', 'replace')}") from e


def models() -> list[str]:
    data = _request("GET", "/models")
    items = data.get("data", data) if isinstance(data, dict) else data
    return [m.get("id") if isinstance(m, dict) else m for m in items]


def classify(state: str, questions: list[dict], model: str = DEFAULT_MODEL) -> dict:
    return _request("POST", "/systemone", {"model": model, "state": state, "questions": questions})


if __name__ == "__main__":
    print("models:", models())
