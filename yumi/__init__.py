"""Public package marker for Yumi.

Quick-start API::

    import yumi

    yumi.register(my_func, "What this function does")
    yumi.run()

This creates a default :class:`YumiAgent` behind the scenes.  For full
control (custom connection code, edge name, multiple agents) use
:class:`yumi.sdk.YumiAgent` directly.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

__all__ = ["__version__", "YumiAgent", "register", "run", "run_in_background", "stop"]

try:
    __version__ = version("yumi")
except PackageNotFoundError:
    __version__ = "0.0.1"

if TYPE_CHECKING:
    from yumi.sdk import YumiAgent

_default_agent: YumiAgent | None = None


def __getattr__(name: str):
    """Lazily expose SDK symbols without making ``import yumi`` import websockets."""
    if name == "YumiAgent":
        from yumi.sdk import YumiAgent

        return YumiAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _get_default_agent() -> YumiAgent:
    global _default_agent
    if _default_agent is None:
        from yumi.sdk import YumiAgent

        _default_agent = YumiAgent()
    return _default_agent


def register(
    func,
    description: str,
    *,
    name: str | None = None,
    params: dict[str, str] | None = None,
    returns: str | None = None,
    timeout: int | None = None,
    require_confirmation: bool = False,
    mode: str = "dynamic",
    context_args: dict | None = None,
    context_label: str | None = None,
    allow_proactive: bool = False,
    always_include: bool = False,
    proactive_context: bool = False,
    proactive_context_args: dict | None = None,
    proactive_context_description: str | None = None,
) -> None:
    """Register a tool on the default agent.

    Equivalent to ``YumiAgent().register(...)`` but uses a shared
    module-level instance so you can write::

        import yumi
        yumi.register(func, "description")
        yumi.run()
    """
    _get_default_agent().register(
        func,
        description,
        name=name,
        params=params,
        returns=returns,
        timeout=timeout,
        require_confirmation=require_confirmation,
        mode=mode,
        context_args=context_args,
        context_label=context_label,
        always_include=always_include,
        allow_proactive=allow_proactive,
        proactive_context=proactive_context,
        proactive_context_args=proactive_context_args,
        proactive_context_description=proactive_context_description,
    )


def run(
    *,
    connection_code: str | None = None,
    edge_name: str | None = None,
) -> None:
    """Run the default agent in the FOREGROUND until interrupted (Ctrl+C).

    For a standalone script (the script itself is the edge). Optional
    *connection_code* / *edge_name* configure the agent before it starts.
    Embedded hosts (a GUI app, a game, another service) should call
    :func:`run_in_background` instead, which returns immediately.
    """
    _get_default_agent().run(connection_code=connection_code, edge_name=edge_name)


def run_in_background(
    *,
    connection_code: str | None = None,
    edge_name: str | None = None,
) -> None:
    """Start the default agent in a background thread and return immediately.

    For embedding the edge in another program that stays alive on its own.
    A standalone script should use :func:`run` so the process doesn't exit.
    """
    _get_default_agent().run_in_background(connection_code=connection_code, edge_name=edge_name)


def stop() -> None:
    """Stop the default agent if it is running."""
    global _default_agent
    if _default_agent is not None:
        _default_agent.stop()
        _default_agent = None
