from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from kumi.core.features.config import load_model_config
from kumi.core.features.proactive.interaction import smart_interaction
from kumi.core.features.proactive.planner import decide_proactive_send
from kumi.core.features.proactive.prompt import build_proactive_prompt, split_proactive_messages
from kumi.core.features.proactive.state import ProactiveStateStore
from kumi.core.features.proactive.tools import proactive_context_lines, proactive_tool_schemas
from kumi.core.platform.tools.normalize import normalize_tool_calls
from kumi.logging_config import get_logger

logger = get_logger(__name__)


def _sample_sleep_seconds(cfg) -> int:
    """Sleep duration before the next proactive check (with optional jitter)."""
    base = max(60, int(cfg.proactive_check_interval_seconds))
    j = float(cfg.proactive_check_interval_jitter_ratio)
    j = max(0.0, min(0.5, j))
    if j <= 0:
        return min(86400, base)
    rng = random.Random(time.time_ns())
    lo = base * (1.0 - j)
    hi = base * (1.0 + j)
    return max(60, min(86400, int(rng.uniform(lo, hi))))


class ProactiveMessageService:
    def __init__(self, bot, *, state_store: ProactiveStateStore | None = None):
        self.bot = bot
        self.state_store = state_store or ProactiveStateStore()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name="kumi-proactive-messaging")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        while not self._stop.is_set():
            cfg = load_model_config()
            if cfg.proactive_mode != "off":
                for session_id in list(cfg.proactive_session_ids):
                    try:
                        await self._maybe_send_for_session(session_id, cfg=cfg)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Proactive messaging failed for session_id=%s", session_id)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_sample_sleep_seconds(cfg))
            except asyncio.TimeoutError:
                pass

    async def _maybe_send_for_session(self, session_id: str, *, cfg) -> None:
        if not session_id or "telegram" not in {c.lower() for c in cfg.proactive_channels}:
            return

        now = datetime.now(timezone.utc)
        state = self.state_store.get(session_id)
        decision = decide_proactive_send(cfg, state, now=now, rng=random.Random())
        if not decision.should_send:
            return

        from kumi.core.platform.runtime.accessors import get_session_lock

        lock = get_session_lock(session_id)
        async with lock:
            # Re-check after acquiring the session lock with a fresh "now" in case a
            # normal chat turn raced ahead and updated state between the pre-lock peek
            # and acquisition.
            now_locked = datetime.now(timezone.utc)
            state = self.state_store.get(session_id)
            decision = decide_proactive_send(cfg, state, now=now_locked, rng=random.Random())
            if not decision.should_send:
                return

            context = await proactive_context_lines()
            prompt = build_proactive_prompt(cfg, state, decision, now=now_locked, context_lines=context)
            text = await self._generate_text(session_id=session_id, prompt=prompt)
            interaction = None
            if (cfg.proactive_mode or "").strip().lower() == "smart":
                interaction = smart_interaction(cfg, state, trigger=decision.trigger)
            parts = split_proactive_messages(text, max_parts=interaction.max_messages if interaction else 3)
            if not parts:
                return

        # Release the session lock before sending — Telegram delivery + the
        # inter-part sleeps add seconds, and a real user message arriving on
        # the same session would otherwise be blocked behind us. Record the
        # send first (with a fresh "now") so daily-limit accounting reflects
        # actual send time, not the LLM-generation start time.
        from kumi.telegram.notify import send_text_to_telegram

        send_started_at = datetime.now(timezone.utc)
        sent_any = False
        for idx, part in enumerate(parts):
            if idx:
                if interaction and interaction.state in ("waiting", "light_nudge"):
                    delay = random.uniform(1.4, 3.4)
                elif interaction and interaction.state in ("reserved", "give_space"):
                    delay = random.uniform(0.9, 1.4)
                else:
                    delay = random.uniform(0.7, 1.8)
                await asyncio.sleep(delay)
            sent = await send_text_to_telegram(session_id, part)
            sent_any = sent_any or sent
        if sent_any:
            self.bot.session_memory(session_id).add_message("assistant", "\n\n".join(parts))
            self.state_store.record_sent(
                session_id,
                trigger=decision.trigger or "check_in",
                at=send_started_at,
                scheduled_slot_key=decision.scheduled_slot_key,
                mark_scheduled_interval=decision.mark_scheduled_interval,
            )

    async def _generate_text(self, *, session_id: str, prompt: str) -> str:
        memory = self.bot.session_memory(session_id)
        messages = memory.get_context(query=prompt)
        messages.append({"role": "user", "content": prompt})
        tools = proactive_tool_schemas()

        full_text = ""
        for _ in range(3):
            tool_calls: list[dict[str, Any]] | None = None
            async for chunk in self.bot.provider.chat_stream(
                model=self.bot.model_name,
                messages=messages,
                tools=tools or None,
                think=False,
            ):
                if chunk.get("type") == "text":
                    full_text += str(chunk.get("content") or "")
                elif chunk.get("type") == "tool_call":
                    tool_calls = normalize_tool_calls(chunk.get("tool_calls") or [])
                    break
            if not tool_calls:
                return full_text.strip()

            messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
            for call in tool_calls:
                name, result = await self._execute_proactive_tool(call)
                messages.append({"role": "tool", "name": name, "content": result})
        return full_text.strip()

    async def _execute_proactive_tool(self, call: dict[str, Any]) -> tuple[str, str]:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        name = str(fn.get("name") or "")
        args = fn.get("arguments") if isinstance(fn.get("arguments"), dict) else {}
        if not name:
            return "unknown", "Error: tool name missing."

        from kumi.core.platform.dispatch.limits import LOCAL_TOOL_TIMEOUT_DEFAULT
        from kumi.core.platform.runtime.accessors import (
            ACTIVE_CONNECTIONS,
            CONFIRMATION_TOOLS,
            DISABLED_TOOLS,
            EDGE_TOOLS_REGISTRY,
            PENDING_TOOL_CALLS,
            edge_tool_key_prefix,
            edge_tool_register_prefix,
            get_tool_timeout,
            parse_edge_connection_key,
            resolve_edge_for_prefixed_tool_name,
        )
        from kumi.core.platform.tools.tool import TOOL_REGISTRY, execute_registered_tool

        if name in TOOL_REGISTRY:
            meta = TOOL_REGISTRY[name]
            if name in DISABLED_TOOLS or name in CONFIRMATION_TOOLS or not meta.get("allow_proactive"):
                return name, "Error: tool is not allowed for proactive messaging."
            try:
                result = await asyncio.wait_for(execute_registered_tool(name, args), timeout=LOCAL_TOOL_TIMEOUT_DEFAULT)
                return name, str(result)
            except Exception as exc:
                return name, f"Error: proactive tool failed: {exc}"

        target_edge = resolve_edge_for_prefixed_tool_name(name)
        if not target_edge:
            return name, "Error: proactive edge tool is offline or not registered."
        entry = EDGE_TOOLS_REGISTRY.get(target_edge, {}).get(name)
        if (
            not entry
            or name in DISABLED_TOOLS
            or name in CONFIRMATION_TOOLS
            or entry.get("require_confirmation")
            or not entry.get("allow_proactive")
        ):
            return name, "Error: edge tool is not allowed for proactive messaging."
        peer = ACTIVE_CONNECTIONS.get(target_edge)
        if peer is None:
            return name, "Error: edge device is offline."

        owner_id, edge_simple = parse_edge_connection_key(target_edge)
        prefix = edge_tool_register_prefix(owner_id, edge_simple) if owner_id else edge_tool_key_prefix(edge_simple)
        original_name = name[len(prefix) :] if name.startswith(prefix) else name
        call_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        PENDING_TOOL_CALLS[call_id] = {"future": future, "edge_name": target_edge, "peer": peer}
        try:
            await peer.send_json({"type": "tool_call", "name": original_name, "arguments": args, "call_id": call_id})
            result = await asyncio.wait_for(future, timeout=get_tool_timeout(name))
            return name, str(result)
        except Exception as exc:
            return name, f"Error: proactive edge tool failed: {exc}"
        finally:
            PENDING_TOOL_CALLS.pop(call_id, None)
