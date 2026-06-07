"""Entry point: ``python -m kumi.demo.smart_home``.

Same pattern as other Kumi edge workspaces: call ``init_kumi()`` once from the
process entrypoint, then run your application (the Smart Home GUI here).
"""

from __future__ import annotations

import argparse


def run_demo(connection_code: str | None = None) -> None:
    from kumi.demo.smart_home.app import SmartHomeGUI
    from kumi.demo.smart_home.bootstrap import init_kumi

    agent = init_kumi(connection_code=connection_code)
    gui = SmartHomeGUI(agent=agent)
    try:
        gui.run()
    finally:
        agent.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Kumi Smart Home demo window")
    parser.add_argument("--connection-code", default=None)
    args = parser.parse_args()
    run_demo(connection_code=args.connection_code)


if __name__ == "__main__":
    main()
