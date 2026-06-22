# Yumi Edge — Python

Use this when your app is written in Python and you want the LLM to call functions inside the same process.

## Quick Start

1. Install the only runtime dependency:

```bash
pip install websockets
```

2. Edit `yumi_tools/python/yumi_setup.py`
3. Set your connection in `yumi_tools/.env` or pass it directly to `YumiAgent(...)`
4. Either call `init_yumi()` from your app, **or** run the setup file alone for a quick test (no `main.py`):

```bash
yumi --run-edge --lang python
```

```bash
# from your project root (where `yumi_tools/` lives)
python -m yumi_tools.python.yumi_setup
```

```bash
# or from yumi_tools/python/
python yumi_setup.py
```

The file includes `if __name__ == "__main__":` so it blocks until Ctrl+C (the edge client runs in a background thread).

## Files In This Folder

```text
yumi_tools/python/
├── README.md
├── __init__.py
├── yumi_setup.py          # edit this
└── yumi_sdk/
    ├── __init__.py
    └── agent_client.py     # bundled SDK, usually leave as-is
```

## Configure Connection

Recommended `.env` file:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My Device
```

You can also pass values directly in `yumi_setup.py`.

## Register Tools

Open `yumi_setup.py` and register your functions:

```python
from .yumi_sdk import YumiAgent
from my_app.actions import jump


def init_yumi():
    agent = YumiAgent()
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
from yumi_tools.python.yumi_setup import init_yumi

agent = init_yumi()
```

Your own program keeps running as usual.

## Notes

- The SDK looks for `yumi_tools/.env` first, then `./.env`
- Tool confirmation choices are stored next to the `.env` file as `.yumi_tool_confirmation.json`
- If your entry script runs from a different working directory, either `cd` to the project root first or pass `connection_code` / `edge_name` directly
