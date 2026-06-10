# Testing

## How to run

```bash
python -m pip install -e ".[dev]"
pytest
```

Optional: statement coverage for the HTTP API package only (no threshold; same command as the **Coverage** CI job):

```bash
python -m pytest --cov=yumi.core.api --cov-report=term-missing
```

Static analysis (also run in CI):

```bash
python -m pyright yumi tests
```

Pyright settings and excludes (for example Reflex UI and edge templates) live under `[tool.pyright]` in the repo root [pyproject.toml](../pyproject.toml). The `yumi/core/features/memory` tree uses a slightly stricter `executionEnvironments` entry (`reportOptionalMemberAccess` / `reportOptionalSubscript` as warnings) as a first step toward stronger typing there.

Run a single file or match a test name:

```bash
pytest tests/test_stream_event.py
pytest tests/ -k stream_event
```

## Configuration

Pytest options live under `[tool.pytest.ini_options]` in the repo root [pyproject.toml](../pyproject.toml) (`testpaths = ["tests"]`).

## What CI runs

- **`pytest`** over the whole `tests/` tree.
- **`ruff check yumi tests`** and **`ruff format --check yumi tests`**
- **`pyright yumi tests`** (dedicated job; Python 3.12)
- **`pytest --cov=yumi.core.api`** (dedicated **Coverage** job; Python 3.12; informational, no fail-under gate)

See [.github/workflows/ci.yml](../.github/workflows/ci.yml) for the full matrix (Python 3.10–3.13, SDK builds, Pyright, and coverage).

Optionally install [pre-commit](https://pre-commit.com/) locally; same hooks as described in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Current scope (kept lightweight on purpose)

By default, tests **do not** start the full `yumi --server` / FastAPI lifespan (avoids pulling models and binding ports in CI). Coverage today roughly includes:

| Area | What is checked |
|------|-----------------|
| HTTP stream shape | NDJSON lines from `stream_event`, plus `/chat` response streaming with a mocked generator |
| Config | `ModelConfig` defaults and CORS env parsing helpers |
| API models | Pydantic models in `yumi.core.platform.http.schemas` |
| App object | `create_app()` returns the same instance as the module-level `app` (no listening socket) |
| Credentials | Encode/decode round-trip plus expiry / kind / scope / signature failures in `yumi.core.platform.security.auth` |
| CLI env | Direct-mode environment selection without launching subprocesses |
| Edge WebSocket | Register handshake, tool mounting, and disconnect cleanup via TestClient WebSocket |
| Health endpoint | `/health` response shape |
| SDK contracts | Wire-format verification across Python, Go, TypeScript, and Java schema builders; register/tool_call/tool_result message shapes |

For end-to-end or HTTP tests with mocks, add cases separately (e.g. `TestClient` with dependencies overridden).
