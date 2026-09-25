"""Search and deterministically browse the same permission-scoped tool catalog."""

from __future__ import annotations

import hashlib
import json

from yumi.core.platform.plugins import get_current_identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.tools.routing import ToolCatalog, ToolCatalogEntry, activate_edge_for_session


def _catalog() -> list[ToolCatalogEntry]:
    runtime = get_default_runtime()
    catalog = ToolCatalog(
        identity=get_current_identity(),
        disabled_tools=runtime.tool_policy.disabled_tools,
        edge_registry=runtime.edge_registry.tools,
    )
    return catalog.core_tools() + catalog.edge_tools()


def _device_id(entry: ToolCatalogEntry) -> str:
    # Do not expose owner IDs in connection keys. IDs only select from the
    # caller's freshly authorized catalog; possession is never authorization.
    return "yumi" if entry.kind == "core" else hashlib.sha256((entry.edge_key or "").encode()).hexdigest()[:16]


def _summary(entry: ToolCatalogEntry) -> dict:
    runtime = get_default_runtime()
    return {
        "name": entry.name,
        "description": entry.description[:500],
        "device": entry.device_name or "Yumi",
        "device_id": _device_id(entry),
        "online": entry.kind == "core" or entry.edge_key in runtime.edge_registry.active_connections,
    }


def _activate(entries: list[ToolCatalogEntry], session_id: str = "default") -> tuple[list[str], list[str]]:
    from yumi.core.platform.providers.budget import fit_tool_schemas
    from yumi.core.platform.runtime.assistant_context import conversation_session
    from yumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
    from yumi.core.platform.tools.routing import load_model_config

    session_id = conversation_session.get() or session_id
    # Check again after retrieval, which may have waited on a query embedding.
    visible = {entry.name: entry for entry in _catalog()}
    names = [entry.name for entry in entries if entry.name in visible]
    candidates = [
        model_visible_tool_schema(visible[name].schema)
        for name in dict.fromkeys(["discover_app_tools", "browse_app_tools", *names])
        if name in visible
    ]
    admitted = {
        schema["function"]["name"]
        for schema in fit_tool_schemas(
            candidates, budget=load_model_config().tool_schema_token_budget, priority_names=names
        )
    }
    activated = [name for name in names if name in admitted]
    for name in activated:
        activate_edge_for_session(session_id, visible[name].edge_key)
    from yumi.core.platform.tools.session_tools import remember_tools

    remember_tools(get_current_identity().user_id, session_id, activated)
    return activated, [name for name in names if name not in admitted]


def discover_app_tools(need: str, session_id: str = "default") -> str:
    """Find matching visible functions. Empty search results do not prove absence."""
    from yumi.core.platform.tools.retrieval import rank_tools, with_companions
    from yumi.core.platform.tools.routing import load_model_config

    need = (need or "").strip()
    if not need:
        return json.dumps({"ok": False, "status": "invalid_request", "error": "need is required"})
    entries = _catalog()
    ranked = rank_tools(need, entries, embed_model=load_model_config().embedding_model)
    matches = with_companions([entry for _, entry in ranked.matches[:6]], entries)
    activated, blocked = _activate(matches, session_id)
    # Do not return descriptions revoked while retrieval was in flight.
    visible = {entry.name for entry in _catalog()}
    matches = [entry for entry in matches if entry.name in visible]
    activated = [name for name in activated if name in visible]
    blocked = [name for name in blocked if name in visible]
    status = "matched" if activated else ("schema_budget_exceeded" if blocked else "no_match")
    if not entries:
        status = "no_visible_tools"
    return json.dumps(
        {
            "ok": True,
            "status": status,
            "retrieval_mode": ranked.mode,
            "retrieval_degraded": ranked.degraded,
            "retrieval_degraded_reason": ranked.degraded_reason,
            "retrieval_elapsed_ms": ranked.elapsed_ms,
            "matches": [_summary(entry) for entry in matches],
            "activated_tool_names": activated,
            "budget_excluded_tool_names": blocked,
            "note": (
                "Only activated_tool_names can be called in the subsequent tool list. "
                "An empty result is not proof that a capability is absent. "
                "If needed, browse_app_tools lists visible devices and pages through their functions without search. "
                "For schema_budget_exceeded, browse a smaller page (limit=1); a single oversized function needs an operator budget adjustment. "
                "Use suitable activated functions directly, even when retrieval_degraded is true. "
                "That flag means semantic ranking was limited, not that the activated functions are unusable. "
                "Do not repeatedly issue the same search; inspect a relevant device before reporting a limitation."
            ),
        },
        ensure_ascii=False,
    )


def browse_app_tools(device: str = "", offset: int = 0, limit: int = 6, catalog_revision: str = "") -> str:
    """List visible devices, or page through a device's tools and activate a page.

    Empty device lists devices. Use its returned device_id (or an exact unique
    device name) for function pages. Pass catalog_revision on subsequent pages.
    """
    entries = sorted(_catalog(), key=lambda entry: entry.name)
    revision = hashlib.sha256(
        json.dumps([(e.name, _device_id(e), e.schema) for e in entries], sort_keys=True).encode()
    ).hexdigest()[:16]
    if catalog_revision and catalog_revision != revision:
        return json.dumps({"ok": False, "status": "catalog_changed", "note": "Restart browsing at offset=0."})
    offset, limit = max(0, int(offset)), max(1, min(20, int(limit)))
    groups: dict[str, list[ToolCatalogEntry]] = {}
    for entry in entries:
        groups.setdefault(_device_id(entry), []).append(entry)
    if not device.strip():
        devices = [
            {
                "device_id": key,
                "device": group[0].device_name or "Yumi",
                "tool_count": len(group),
                "online": _summary(group[0])["online"],
                "capabilities_preview": [
                    {"name": e.name.rsplit("__", 1)[-1], "description": e.description[:120]} for e in group[:4]
                ],
                "preview_complete": len(group) <= 4,
            }
            for key, group in sorted(groups.items())
        ]
        total = len(devices)
        result = {"devices": devices[offset : offset + limit], "status": "devices"}
    else:
        keys = [
            key
            for key, group in groups.items()
            if device.strip() == key or device.strip() == (group[0].device_name or "Yumi")
        ]
        if len(keys) != 1:
            return json.dumps(
                {
                    "ok": False,
                    "status": "device_not_visible" if not keys else "ambiguous_device",
                    "note": "List devices with device='' and use a returned device_id. Unavailable and unauthorized devices are not disclosed.",
                }
            )
        group = groups[keys[0]]
        page = group[offset : offset + limit]
        activated, blocked = _activate(page)
        total = len(group)
        result = {
            "status": "tools",
            "device_id": keys[0],
            "matches": [_summary(e) for e in page],
            "activated_tool_names": activated,
            "budget_excluded_tool_names": blocked,
            "note": "Only activated_tool_names are callable in the subsequent tool list. For excluded functions retry a smaller page (limit=1). If a single function still exceeds the schema budget, report that limitation.",
        }
    result.update(
        {
            "ok": True,
            "catalog_revision": revision,
            "offset": offset,
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }
    )
    return json.dumps(result, ensure_ascii=False)
