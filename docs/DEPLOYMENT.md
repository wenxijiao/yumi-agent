# Deployment

Yumi ships as a standalone Python package. `pip install yumi-agent` gives you a
runnable local-first agent server, CLI, HTTP API, and Edge SDK templates.

## Install

```bash
pip install yumi-agent            # core (Ollama provider, HTTP API, CLI)
pip install "yumi-agent[all]"     # + UI, voice, STT, Telegram, cloud providers
```

Optional extras (combine as needed): `ui`, `voice`, `stt`, `telegram`,
`openai`, `gemini`, `claude`, `providers` (all cloud providers), `files`.

Python 3.10+.

## First run

```bash
yumi --setup        # interactive: pick chat/embedding provider + credentials
yumi --server       # start the FastAPI server (default 127.0.0.1:8000)
yumi --chat         # terminal chat against a running server
yumi --ui           # launch the Reflex web UI (needs the [ui] extra)
```

`python -m yumi.core.api` also starts the server. It binds `127.0.0.1:8000` by
default (loopback only; the local API has no built-in user auth). Expose it on
your LAN with `YUMI_HOST=0.0.0.0` (or `yumi --server --host 0.0.0.0`) only on a
trusted network.

## Configuration

All settings live in `~/.yumi/config.json` (written atomically, `0o600`) and can
be overridden by environment variables. The full schema is `ModelConfig`
(`yumi/core/features/config/model.py`); see [`CONFIGURATION.md`](CONFIGURATION.md)
for every key and its `YUMI_*` env override.

Secrets (API keys, Telegram/LINE tokens, `lan_secret`) are stored in that file —
keep `~/.yumi/` private. Never commit it.

## Docker

```bash
docker compose up        # uses the bundled docker-compose.yml + Dockerfile
```

Mount `~/.yumi` (or provide `YUMI_*` env vars) so config/credentials persist
across container restarts. Expose `8000` for the HTTP API.

## Production notes

* **Bind address / TLS.** The server listens on loopback by default. To serve a
  LAN or the internet, front it with a reverse proxy (nginx/Caddy) terminating
  TLS; do not expose `:8000` directly.
* **CORS.** Set `YUMI_CORS_ORIGINS` to the exact origins that need browser
  access. `*` together with `YUMI_CORS_ALLOW_CREDENTIALS=true` is rejected at
  startup.
* **Health check.** `GET /health` returns readiness — wire it to your
  orchestrator's liveness/readiness probes.
* **Graceful shutdown.** SIGTERM drains in-flight work before exit.

## Verifying a clean install

```bash
python -m build --wheel
python -m venv /tmp/venv && /tmp/venv/bin/pip install dist/yumi_agent-*.whl
/tmp/venv/bin/python -c "import yumi; print('ok')"
/tmp/venv/bin/yumi --help
```

This is the same smoke check run in CI to guarantee the package installs and
imports standalone.
