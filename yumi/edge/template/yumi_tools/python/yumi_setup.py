"""
Yumi Edge — Python tool registration

Import your own functions and register them with a description.
Parameter types are auto-extracted from type hints, and parameter
descriptions from the docstring Args section.

Two ways to run::

    # Standalone — this script IS the edge (blocks until Ctrl+C):
    python yumi_setup.py

    # Embedded — start it from your own program and keep going:
    from yumi_tools.python.yumi_setup import init_yumi
    init_yumi().run_in_background()   # returns immediately

Requires: pip install websockets
"""

import os

try:
    from .yumi_sdk import YumiAgent
except ImportError:
    # ``python yumi_setup.py`` from ``yumi_tools/python/`` (not as a package)
    from yumi_sdk import YumiAgent

# ── Import your tool functions ──
# from my_app.actions import jump, run


# ── Example tool (replace with your own) ──
# A minimal tool so a freshly scaffolded edge is testable right away: run this
# script, then ask Yumi to "ping my edge" — it calls ping() and shows the
# returned text. Delete it once your own tools work.
def ping(message: str = "hello") -> str:
    """Echo a message back so you can confirm the edge is connected.

    Args:
        message: Text to echo back.
    """
    return f"pong: {message}"


def init_yumi():
    # `yumi --edge` wrote your edge name, connection code, and server to
    # yumi_tools/.env. Point YumiAgent at that file by its location on disk (not
    # the current working directory), so it loads no matter where you launch from
    # — VS Code's Run button, a different folder, etc. Pass args only to override
    # in code (e.g. one process running several edges):
    #   YumiAgent(edge_name="weather-pi", connection_code="yumi-lan_...")
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    agent = YumiAgent(env_path=env_path)

    # ── Register tools: func + description ──
    # The description tells the AI when and how to use the tool.
    # Tool name and parameter types are auto-extracted from the function.
    #
    # This example is registered in "pinned" mode so the model always sees it
    # (handy for a first end-to-end test). Replace it with your own tools.
    agent.register(ping, "Ping the edge and echo a message back", mode="pinned")
    #
    # agent.register(jump, "Make the character jump")
    # agent.register(run, "Make the character run at a given speed")
    #
    # Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
    # agent.register(delete_all, "Delete all data", require_confirmation=True)
    #
    # Exposure mode (pick one per tool):
    #   "dynamic" (default) — model sees it when relevant (dynamic retrieval)
    #   "pinned"  — schema exposed to the model every turn
    #   "autorun" — run before each reply, result injected as context the agent
    #               always sees (model gets the result, not the tool)
    # agent.register(get_status, "Read current app status", mode="pinned")
    # agent.register(get_user_context, "User's recent mood and plans", mode="autorun")
    #
    # Tool confirmation choices (Tools page / chat "always allow") are saved next to your
    # .env as .yumi_tool_confirmation.json (override with YUMI_TOOL_CONFIRMATION_PATH).

    # Tools are registered; the caller decides how to run:
    #   standalone script:  init_yumi().run()                (blocks until Ctrl+C)
    #   embedded in an app:  init_yumi().run_in_background()  (returns at once)
    return agent


if __name__ == "__main__":
    import logging
    import sys

    # Surface the SDK's connection logs ("Connected as [name] with N tool(s).").
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print("Yumi edge running (standalone). Press Ctrl+C to stop.", file=sys.stderr)
    init_yumi().run()
