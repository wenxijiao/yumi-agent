# Kumi Edge — Python

Use this when your app is written in Python and you want the LLM to call functions inside the same process.

## Quick Start

1. Install the only runtime dependency:

```bash
pip install websockets
```

2. Edit `kumi_tools/python/kumi_setup.py`
3. Set your connection in `kumi_tools/.env` or pass it directly to `KumiAgent(...)`
4. Either call `init_kumi()` from your app, **or** run the setup file alone for a quick test (no `main.py`):

```bash
# from your project root (where `kumi_tools/` lives)
python -m kumi_tools.python.kumi_setup
```

```bash
# or from kumi_tools/python/
python kumi_setup.py
```

The file includes `if __name__ == "__main__":` so it blocks until Ctrl+C (the edge client runs in a background thread).

## Files In This Folder

```text
kumi_tools/python/
├── README.md
├── __init__.py
├── kumi_setup.py          # edit this
└── kumi_sdk/
    ├── __init__.py
    └── agent_client.py     # bundled SDK, usually leave as-is
```

## Configure Connection

Recommended `.env` file:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Device
```

You can also pass values directly in `kumi_setup.py`.

## Register Tools

Open `kumi_setup.py` and register your functions:

```python
from .kumi_sdk import KumiAgent
from my_app.actions import jump


def init_kumi():
    agent = KumiAgent()
    agent.register(jump, "Make the character jump")
    agent.run_in_background()
    return agent
```

Python is the most automatic SDK:

- tool name comes from `func.__name__`
- parameter types come from type hints
- parameter descriptions can come from the docstring `Args:` section

Use `require_confirmation=True` for dangerous actions.

## Start It From Your App

```python
from kumi_tools.python.kumi_setup import init_kumi

agent = init_kumi()
```

Your own program keeps running as usual.

## Notes

- The SDK looks for `kumi_tools/.env` first, then `./.env`
- Tool confirmation choices are stored next to the `.env` file as `.kumi_tool_confirmation.json`
- If your entry script runs from a different working directory, either `cd` to the project root first or pass `connection_code` / `edge_name` directly
