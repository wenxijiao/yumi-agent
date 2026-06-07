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

__all__ = ["__version__", "YumiAgent", "register", "run", "stop"]

__version__ = "0.2.0"

from yumi.sdk import YumiAgent as YumiAgent

_default_agent: YumiAgent | None = None


def _get_default_agent() -> YumiAgent:
    global _default_agent
    if _default_agent is None:
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
    always_include: bool = False,
    allow_proactive: bool = False,
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
    """Start the default agent in the background.

    Optional *connection_code* and *edge_name* are applied to the
    default agent before starting.  If the agent is already running
    this is a no-op.
    """
    agent = _get_default_agent()
    if connection_code is not None:
        agent._connection_code = connection_code
    if edge_name is not None:
        agent._edge_name = edge_name
    agent.run_in_background()


def stop() -> None:
    """Stop the default agent if it is running."""
    global _default_agent
    if _default_agent is not None:
        _default_agent.stop()
        _default_agent = None
