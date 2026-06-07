"""Provider-facing tool schema assembly."""

from __future__ import annotations

_TOOL_RUNTIME_METADATA_KEYS = {
    "allow_proactive",
    "proactive_context",
    "proactive_context_args",
    "proactive_context_description",
    "timeout",
    "require_confirmation",
    "always_include",
}


def model_visible_tool_schema(schema: dict) -> dict:
    """Return a provider-facing schema without Kumi-only runtime metadata."""
    return {k: v for k, v in dict(schema).items() if k not in _TOOL_RUNTIME_METADATA_KEYS}


class ToolCatalog:
    """Combines local tools and edge tools for one runtime."""

    def __init__(self, runtime):
        self._runtime = runtime

    def all_tool_schemas(self, identity=None) -> list:
        from kumi.core.plugins import get_current_identity, get_edge_scope
        from kumi.core.tool import TOOL_REGISTRY

        if identity is None:
            identity = get_current_identity()

        disabled = self._runtime.tool_policy.disabled_tools
        all_tools = []
        for name, tool_data in TOOL_REGISTRY.items():
            if name not in disabled:
                all_tools.append(model_visible_tool_schema(tool_data["schema"]))

        edge_extras = get_edge_scope().filter_edge_tool_schemas(
            identity,
            self._runtime.edge_registry.tools,
            disabled,
        )
        all_tools.extend(edge_extras)
        return all_tools

    def tool_timeout(self, prefixed_name: str, default: int) -> int:
        for edge_tools in self._runtime.edge_registry.tools.values():
            entry = edge_tools.get(prefixed_name)
            if entry and entry.get("timeout") is not None:
                return entry["timeout"]
        return default
