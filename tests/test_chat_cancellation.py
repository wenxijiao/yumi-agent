import asyncio
import contextlib
import uuid

from yumi.core.features.chat import cancellation


def test_cancel_is_scoped_to_owner_and_request_and_handles_early_cancel():
    async def run():
        request_id = str(uuid.uuid4())
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def chat():
            assert cancellation.register("alice", request_id)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancellation.finish("alice", request_id)
                stopped.set()

        task = asyncio.create_task(chat())
        await started.wait()
        assert await cancellation.cancel("bob", request_id)
        assert not stopped.is_set()
        assert await cancellation.cancel("alice", str(uuid.uuid4()))
        assert not stopped.is_set()
        assert await cancellation.cancel("alice", request_id)
        assert stopped.is_set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        early = str(uuid.uuid4())
        assert await cancellation.cancel("alice", early)
        assert not cancellation.register("alice", early)
        assert not cancellation.register("alice", request_id)

    asyncio.run(run())


def test_chat_stream_cancellation_stops_generator_and_releases_registry(monkeypatch):
    from types import SimpleNamespace

    from yumi.core.features.chat import router
    from yumi.core.platform.http.schemas import ChatRequest
    from yumi.core.platform.runtime.assistant_context import active_requests

    quota = SimpleNamespace(check_chat_allowed=lambda _: (True, None), check_token_quota=lambda _: (True, None))
    monkeypatch.setattr(router, "get_quota_policy", lambda: quota)
    monkeypatch.setattr(router, "get_session_scope", lambda: SimpleNamespace(qualify_session_http=lambda _, sid: sid))
    monkeypatch.setattr(router, "audit_event", lambda *_, **__: None)

    async def run():
        started, stopped = asyncio.Event(), asyncio.Event()
        request_id = str(uuid.uuid4())

        async def generate(*_, **__):
            started.set()
            try:
                await asyncio.Event().wait()
                yield {"type": "text", "content": "must not arrive"}
            finally:
                stopped.set()

        monkeypatch.setattr(router, "generate_chat_events", generate)
        response = await router.chat_endpoint(
            None,
            SimpleNamespace(user_id="alice"),
            ChatRequest(prompt="hello", session_id="test-cancel", client_request_id=request_id),
        )

        async def consume():
            async for _ in response.body_iterator:
                raise AssertionError("Old turn emitted a result")

        task = asyncio.create_task(consume())
        await started.wait()
        result = await router.cancel_chat_endpoint(
            SimpleNamespace(user_id="alice"), router.CancelChatRequest(client_request_id=request_id)
        )
        assert result == {"status": "cancelled"}
        assert stopped.is_set()
        assert "test-cancel" not in active_requests
        assert ("alice", request_id) not in cancellation._tasks
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())
