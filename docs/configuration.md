# Configuration

Two files, both outside version control once you have copied them:

- `config/inference.env` - hosts, ports, root path and secrets locations
- `config/models.json` - models, ports, VRAM budgets, runtimes

## `config/inference.env`

Copy `config/inference.env.example` to `config/inference.env`. The gateway reads it
on startup; real environment variables always win over the file.

| Variable | Default | Meaning |
|---|---|---|
| `INFERENCE_HOST` | `127.0.0.1` | address clients use to reach the gateway |
| `INFERENCE_PORT` | `8080` | gateway port |
| `INFERENCE_BIND` | `0.0.0.0` | interface the gateway listens on |
| `INFERENCE_ROOT` | `C:\local-inference` | models, binaries, logs, caches |
| `GATEWAY_KEY_FILE` | `<secrets>/gateway.key` | bearer token file |
| `TYPESAFE_API_KEY` | - | enables `POST /v1/classify` |
| `HF_TOKEN` | - | only for gated Hugging Face repositories |

Client-side variables (`clients/infer.py`): `INFER_HOST`, `GATEWAY_KEY`,
`GATEWAY_KEY_FILE`.

Service-level overrides (all optional) are documented at the top of each module in
`services/*/app.py`, for example `VOXCPM_REF_AUDIO`, `ASR_BACKEND`,
`RERANK_OPENVINO_DEVICE`, `VIDEO_VAE`.

## `config/models.json`

| Field | Meaning |
|---|---|
| `path` | file path relative to `INFERENCE_ROOT` |
| `source` | Hugging Face repository the file comes from |
| `port` | local port the service listens on |
| `resident` | start with the stack, or only on demand |
| `vram_mb` / `idle_stop_seconds` | budgeting hints used by docs and the job service |
| `hosted` | an external API rather than a local process |
| `why` | the measurement or constraint behind the choice |

Ports are what the gateway proxies to; change them freely as long as they do not
collide (note that Breeze-TTS-2.cpp also binds `port + 1` for its WebSocket, so
avoid a service immediately after it).

## Secrets

- `scripts/new-key.ps1` (Windows) or `scripts/new-key.sh` (Unix) writes a 32-byte
  random bearer token to `<secrets>/gateway.key` with owner-only permissions.
- TypeSafe keys go in `<secrets>/typesafe.key` or `TYPESAFE_API_KEY`.
- Nothing secret belongs in `config/inference.env` if the file might be shared;
  `config/inference.env` is gitignored for that reason.

## Autostart and cleanup

- `scripts/register-autostart.ps1` registers a boot-triggered task with an S4U
  principal: it runs whether or not anyone is logged in, and the GPU remains
  visible to it.
- `scripts/free-vram.ps1` stops resident services by port so an exclusive job can
  own the GPU; `start-stack.ps1` brings them back.
- If you run CI or other heavy work on the same machine, give it a lower process
  priority than the inference services, and cap its build directory.
