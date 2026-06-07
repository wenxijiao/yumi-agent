"""HTTP helpers for Telegram/LINE bridges: session & global system prompt APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from yumi.core.platform.security.connection import ConnectionConfig


def _api_url(connection: ConnectionConfig, path: str) -> str:
    if connection.mode == "relay":
        return f"{connection.base_url.rstrip('/')}/v1{path}"
    return f"{connection.base_url.rstrip('/')}{path}"


def _session_prompt_path(session_id: str) -> str:
    return f"/config/session-prompt/{quote(session_id, safe='/')}"


async def http_get_session_prompt(connection: ConnectionConfig, session_id: str) -> tuple[dict[str, Any] | None, str]:
    url = _api_url(connection, _session_prompt_path(session_id))
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            return None, r.text[:500]
        return r.json(), ""


async def http_get_global_system_prompt(
    connection: ConnectionConfig,
) -> tuple[dict[str, Any] | None, str]:
    url = _api_url(connection, "/config/system-prompt")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            return None, r.text[:500]
        return r.json(), ""


async def http_put_session_prompt(connection: ConnectionConfig, session_id: str, text: str) -> tuple[bool, str]:
    url = _api_url(connection, _session_prompt_path(session_id))
    headers = {**connection.auth_headers(), "Content-Type": "application/json"}
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.put(url, headers=headers, json={"system_prompt": text})
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


async def http_delete_session_prompt(connection: ConnectionConfig, session_id: str) -> tuple[bool, str]:
    url = _api_url(connection, _session_prompt_path(session_id))
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.delete(url, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


def truncate_for_bot_display(text: str, max_chars: int = 3000) -> str:
    s = text if isinstance(text, str) else str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def format_effective_prompt_reply(*, effective: str, source_label: str) -> str:
    return f"Current system prompt ({source_label}):\n\n{truncate_for_bot_display(effective)}"
