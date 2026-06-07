"""Entry point: ``python -m yumi.demo.planner``.

Same pattern as other Yumi edge workspaces: call ``init_yumi()`` once from the
process entrypoint, then run your app. For this demo, ``Tk`` is created first,
then ``init_yumi()`` (macOS-friendly when two GUI demos run under ``yumi --demo``).
"""

from __future__ import annotations

import argparse


def run_demo(connection_code: str | None = None) -> None:
    import tkinter as tk

    from yumi.demo.planner.app import COL_BG, PlannerGUI
    from yumi.demo.planner.bootstrap import init_yumi

    root = tk.Tk()
    root.title("Yumi Planner — Schedule Demo")
    root.configure(bg=COL_BG)
    root.resizable(False, False)
    root.geometry("980x780")

    agent = init_yumi(connection_code=connection_code)
    gui = PlannerGUI(root, agent)
    try:
        gui.run()
    finally:
        agent.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Yumi Planner demo window")
    parser.add_argument("--connection-code", default=None)
    args = parser.parse_args()
    run_demo(connection_code=args.connection_code)


if __name__ == "__main__":
    main()
