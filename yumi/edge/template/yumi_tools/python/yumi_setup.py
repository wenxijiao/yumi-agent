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

try:
    from .yumi_sdk import YumiAgent
except ImportError:
    # ``python yumi_setup.py`` from ``yumi_tools/python/`` (not as a package)
    from yumi_sdk import YumiAgent

# ── Import your tool functions ──
# from my_app.actions import jump, run


def init_yumi():
    agent = YumiAgent(
        # connection_code="yumi-lan_...",  # or set YUMI_CONNECTION_CODE in .env
        # edge_name="My Device",              # or set EDGE_NAME in .env
    )

    # ── Register tools: func + description ──
    # The description tells the AI when and how to use the tool.
    # Tool name and parameter types are auto-extracted from the function.
    #
    # agent.register(jump, "Make the character jump")
    # agent.register(run, "Make the character run at a given speed")
    #
    # Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
    # agent.register(delete_all, "Delete all data", require_confirmation=True)
    #
    # High-value tools that should bypass dynamic routing every turn:
    # agent.register(get_status, "Read current app status", always_include=True)
    #
    # Read-only tools can opt in to proactive messaging context:
    # agent.register(get_status, "Read current app status", allow_proactive=True, proactive_context=True)
    #
    # Tool confirmation choices (Tools page / chat "always allow") are saved next to your
    # .env as .yumi_tool_confirmation.json (override with YUMI_TOOL_CONFIRMATION_PATH).

    # Tools are registered; the caller decides how to run:
    #   standalone script:  init_yumi().run()                (blocks until Ctrl+C)
    #   embedded in an app:  init_yumi().run_in_background()  (returns at once)
    return agent


if __name__ == "__main__":
    import sys

    print("Yumi edge running (standalone). Press Ctrl+C to stop.", file=sys.stderr)
    init_yumi().run()
