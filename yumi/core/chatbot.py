from __future__ import annotations

from collections import OrderedDict

from yumi.core.features.chat import debug_trace as chat_debug_trace
from yumi.core.features.config import load_model_config
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.config.paths import CONFIG_DIR, ensure_config_dir
from yumi.core.features.memory.memory import Memory
from yumi.core.features.prompts.composer import compose_messages, messages_have_multimodal_images
from yumi.core.platform.plugins import get_session_scope
from yumi.core.platform.providers.base import BaseLLMProvider
from yumi.core.platform.providers.diagnostics import provider_name, write_provider_failure_diagnostic
from yumi.core.platform.providers.error_classify import is_multimodal_vision_rejection
from yumi.core.platform.streaming.think_parser import ThinkTagParser
from yumi.logging_config import get_logger

logger = get_logger(__name__)

_MEMORY_CACHE_MAX = 64


class YumiBot:
    """High-level chat orchestration: memory, streaming, and tool-call handoff."""

    def __init__(
        self,
        provider: BaseLLMProvider,
        model_name: str,
        think: bool = False,
        *,
        runtime_config: ModelConfig | None = None,
    ):
        self.provider = provider
        self.model_name = model_name
        self.think = think
        self._runtime_config = runtime_config
        self.memories: OrderedDict[str, Memory] = OrderedDict()

    def _storage_dir_for_session(self, session_id: str) -> str | None:
        # OSS default: shared memory dir. Enterprise plugins resolve per-user
        # storage via the MemoryFactory port, so we just delegate.
        owner = get_session_scope().owner_user_from_session_id(session_id)
        if owner == "_local":
            return None
        ensure_config_dir()
        d = CONFIG_DIR / "users" / owner / "memory"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _get_memory(self, session_id: str = "default"):
        if session_id in self.memories:
            self.memories.move_to_end(session_id)
        else:
            sd = self._storage_dir_for_session(session_id)
            self.memories[session_id] = Memory(session_id=session_id, storage_dir=sd)
            if len(self.memories) > _MEMORY_CACHE_MAX:
                self.memories.popitem(last=False)
        return self.memories[session_id]

    def session_memory(self, session_id: str = "default") -> Memory:
        """LanceDB-backed memory for this chat session (same instance as ``chat_stream`` uses)."""
        return self._get_memory(session_id)

    async def warm_up(self):
        await self.provider.warm_up(self.model_name)

    async def chat_stream(
        self,
        prompt: str | None = None,
        session_id: str = "default",
        tools: list | None = None,
        ephemeral_messages: list | None = None,
        think: bool | None = None,
    ):
        """Core streaming chat flow with function-calling support."""
        memory = self._get_memory(session_id)

        if prompt:
            user_message_id = memory.add_message("user", prompt)

        cfg = self._runtime_config or load_model_config()
        messages = compose_messages(
            memory,
            prompt=prompt,
            tools=tools,
            ephemeral_messages=ephemeral_messages,
            cfg=cfg,
            upload_mode="vision",
        )

        if chat_debug_trace.is_tracing(session_id):
            chat_debug_trace.append_llm_provider_request(
                session_id,
                model=self.model_name,
                messages=messages,
                tools=tools,
            )

        use_think = think if think is not None else self.think
        full_response = ""
        full_thought = ""
        parser = ThinkTagParser()

        def _record_provider_failure(exc: Exception, msgs: list[dict], phase: str) -> None:
            path = write_provider_failure_diagnostic(
                exc=exc,
                provider=provider_name(self.provider),
                model=self.model_name,
                messages=msgs,
                tools=tools,
                session_id=session_id,
                prompt=prompt,
                phase=phase,
            )
            if path:
                logger.error("Provider request failed; wrote diagnostic snapshot to %s", path)

        async def _consume_stream(msgs: list[dict]):
            nonlocal full_response, full_thought, parser
            async for chunk in self.provider.chat_stream(
                model=self.model_name,
                messages=msgs,
                tools=tools,
                think=use_think,
            ):
                if chunk.get("type") == "usage":
                    yield chunk
                    continue
                if chunk["type"] == "tool_call":
                    yield chunk
                    return
                # Providers that emit reasoning on a dedicated channel (e.g.
                # DeepSeek's ``delta.reasoning_content``) bypass the inline
                # ``<think>...</think>`` parser. Accumulate into full_thought
                # so it can be persisted alongside the assistant message and
                # replayed on the next turn (required by DeepSeek when the
                # turn also produced tool_calls).
                if chunk["type"] == "thought":
                    segment = chunk.get("content", "")
                    if segment:
                        full_thought += segment
                    yield chunk
                    continue

                content = chunk.get("content", "")
                if content:
                    for kind, segment in parser.feed(content):
                        if kind == "thought":
                            if use_think:
                                full_thought += segment
                            yield {"type": "thought", "content": segment}
                        else:
                            full_response += segment
                            yield {"type": "text", "content": segment}
            # Drain any text the parser was holding back while waiting for a
            # possible tag completion that never arrived.
            for kind, segment in parser.flush():
                if kind == "thought":
                    if use_think:
                        full_thought += segment
                    yield {"type": "thought", "content": segment}
                else:
                    full_response += segment
                    yield {"type": "text", "content": segment}

        try:
            async for chunk in _consume_stream(messages):
                yield chunk
        except Exception as exc:
            if is_multimodal_vision_rejection(exc) and messages_have_multimodal_images(messages):
                logger.info(
                    "Multimodal request rejected; retrying chat as text-only: %s",
                    exc,
                )
                full_response = ""
                full_thought = ""
                parser = ThinkTagParser()
                messages_fb = compose_messages(
                    memory,
                    prompt=prompt,
                    tools=tools,
                    ephemeral_messages=ephemeral_messages,
                    cfg=cfg,
                    upload_mode="no_vision",
                )
                if chat_debug_trace.is_tracing(session_id):
                    chat_debug_trace.append_llm_provider_request(
                        session_id,
                        model=self.model_name,
                        messages=messages_fb,
                        tools=tools,
                        note="text_only_fallback_after_vision_rejection",
                    )
                try:
                    async for chunk in _consume_stream(messages_fb):
                        yield chunk
                except Exception as fb_exc:
                    _record_provider_failure(fb_exc, messages_fb, "chat_stream_text_only_fallback")
                    if prompt:
                        memory.delete_message(user_message_id)
                    raise
            else:
                _record_provider_failure(exc, messages, "chat_stream")
                if prompt:
                    memory.delete_message(user_message_id)
                raise

        if full_response:
            memory.add_message(
                "assistant",
                full_response,
                thought=full_thought.strip() if use_think and full_thought.strip() else None,
            )

    def clear_memory(self, session_id: str = "default"):
        memory = self._get_memory(session_id)
        memory.clear_history()
        self.memories.pop(session_id, None)

    async def change_model(self, new_model: str):
        if self.model_name == new_model:
            return

        old_model = self.model_name
        await self.provider.shutdown(old_model)

        logger.info("Changing model from %s to %s", old_model, new_model)
        self.model_name = new_model

        await self.provider.warm_up(new_model)
