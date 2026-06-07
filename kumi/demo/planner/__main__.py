"""Entry point: ``python -m kumi.demo.planner``.

Same pattern as other Kumi edge workspaces: call ``init_kumi()`` once from the
process entrypoint, then run your app. For this demo, ``Tk`` is created first,
then ``init_kumi()`` (macOS-friendly when two GUI demos run under ``kumi --demo``).
"""

from __future__ import annotations

import argparse


def run_demo(connection_code: str | None = None) -> None:
    import tkinter as tk

    from kumi.demo.planner.app import COL_BG, PlannerGUI
    from kumi.demo.planner.bootstrap import init_kumi

    root = tk.Tk()
    root.title("Kumi Planner — Schedule Demo")
    root.configure(bg=COL_BG)
    root.resizable(False, False)
    root.geometry("980x780")

    agent = init_kumi(connection_code=connection_code)
    gui = PlannerGUI(root, agent)
    try:
        gui.run()
    finally:
        agent.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Kumi Planner demo window")
    parser.add_argument("--connection-code", default=None)
    args = parser.parse_args()
    run_demo(connection_code=args.connection_code)


if __name__ == "__main__":
    main()
