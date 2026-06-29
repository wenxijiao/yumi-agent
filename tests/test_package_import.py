"""Package-level import contract tests."""

import subprocess
import sys
import textwrap


def test_import_yumi_does_not_import_websocket_sdk_dependency():
    """The CLI imports ``yumi.cli``, so the package root must stay lightweight."""
    code = textwrap.dedent(
        """
        import builtins

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "websockets" or name.startswith("websockets."):
                raise RuntimeError("import yumi should not import websockets")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import

        import yumi

        assert yumi.__version__
        """
    )

    subprocess.run([sys.executable, "-c", code], check=True)


def test_cli_help_does_not_import_runtime_dependencies():
    """Help/version paths should not need the full server/runtime dependency graph."""
    code = textwrap.dedent(
        """
        import builtins
        import sys

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in {"pydantic", "websockets"} or name.startswith(("pydantic.", "websockets.")):
                raise RuntimeError(f"yumi --help should not import {name}")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = guarded_import
        sys.argv = ["yumi", "--help"]

        import yumi.cli

        yumi.cli.main()
        """
    )

    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
