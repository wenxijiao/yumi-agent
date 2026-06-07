"""Launch the Kumi demo suite.

``kumi --demo`` starts two independent Python GUI applications:

- Smart Home
- Planner (schedule)

Each process runs its own ``KumiAgent`` and registers a separate tool host.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time


def _spawn(module: str, connection_code: str | None) -> subprocess.Popen:
    cmd = [sys.executable, "-m", module]
    if connection_code:
        cmd.extend(["--connection-code", connection_code])
    return subprocess.Popen(cmd)


def run_demo_suite(connection_code: str | None = None) -> None:
    modules = ("kumi.demo.smart_home", "kumi.demo.planner")
    for m in modules:
        try:
            importlib.import_module(m)
        except ImportError as e:
            print()
            print(f"  Cannot import demo module {m}: {e}")
            print("  From your Kumi clone run: pip install -e .")
            print()
            raise SystemExit(1) from e

    procs: list[subprocess.Popen] = []
    for i, m in enumerate(modules):
        if i:
            time.sleep(0.35)
        procs.append(_spawn(m, connection_code))

    for mod, proc in zip(modules, procs, strict=True):
        print(f"  Started {mod} (pid {proc.pid})")

    # If a child exits immediately (missing package, tkinter/SDL, import error),
    # the parent would otherwise sit in the wait loop with only one window open.
    time.sleep(1.0)
    for mod, proc in zip(modules, procs, strict=True):
        code = proc.poll()
        if code is not None:
            print()
            print(f"  Demo process exited early: {mod} (exit code {code})")
            print(f"  Re-run alone to see the error: {sys.executable} -m {mod}")
            print("  Common fixes: run from the repo root with `pip install -e .`, or check")
            print("  that the Planner window is not hidden behind Smart Home (Dock / Mission Control).")
            print()

    try:
        while any(proc.poll() is None for proc in procs):
            time.sleep(0.5)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 2.0
        for proc in procs:
            if proc.poll() is None:
                remaining = max(0.1, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    proc.kill()
