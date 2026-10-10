"""Speaker readiness cannot execute tools or acknowledge another account's turn."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from yumi.core.features.chat import media_prepare as prepare
from yumi.core.features.chat.router import MediaReadyRequest, voice_media_ready
from yumi.core.platform.dispatch.context import ToolInvocation
from yumi.core.platform.http.events import MediaPrepareEvent, parse_chat_event
from yumi.core.platform.runtime.assistant_context import message_media


def test_acknowledgement_is_owner_bound_one_shot_and_expires():
    async def run():
        with prepare.preparation("alice") as (key, future):
            with pytest.raises(HTTPException) as exc:
                prepare.acknowledge("bob", key, True)
            assert exc.value.status_code == 404 and not future.done()
            assert await voice_media_ready(
                SimpleNamespace(user_id="alice"), MediaReadyRequest(preparation_id=key, ready=True)
            ) == {"ok": True}
            assert await prepare.wait_until_ready(future)
            with pytest.raises(HTTPException):
                prepare.acknowledge("alice", key, True)
        with pytest.raises(HTTPException):
            prepare.acknowledge("alice", key, True)
        assert not prepare._pending

    asyncio.run(run())


@pytest.mark.parametrize("case", ["negative", "timeout", "cancel"])
def test_unready_and_cancelled_waits_are_cleaned_up(case, monkeypatch):
    monkeypatch.setattr(prepare, "PREPARE_TIMEOUT", 0.01)

    async def run():
        with prepare.preparation("alice") as (key, future):
            if case == "negative":
                prepare.acknowledge("alice", key, False)
            if case == "cancel":
                task = asyncio.create_task(prepare.wait_until_ready(future))
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert not await prepare.wait_until_ready(future)
        assert not prepare._pending
        with pytest.raises(HTTPException):
            prepare.acknowledge("alice", key, True)

    asyncio.run(run())


@pytest.mark.parametrize(
    "opt_in,kind,name,terminal,expected",
    [
        (True, "edge", "music_play", True, True),
        (True, "edge", "music_play_request", True, True),
        (False, "edge", "music_play", True, False),
        (True, "edge", "music_status", True, False),
        (True, "local", "music_play", True, False),
        (True, "edge", "music_play", False, False),
    ],
)
def test_only_opted_in_music_side_effects_are_gated(opt_in, kind, name, terminal, expected):
    token = message_media.set({"prepare_media_output": opt_in})
    try:
        inv = ToolInvocation(
            kind=kind,
            func_name=name,
            tool_message_name=name,
            args={},
            original_tool_name=name,
            reply_on_success=not terminal,
        )
        assert prepare.needs_preparation([inv]) is expected
    finally:
        message_media.reset(token)


def test_protocol_is_typed_and_rejects_string_boolean():
    with pytest.raises(ValidationError):
        MediaReadyRequest(preparation_id="a" * 32, ready="true")
    event = MediaPrepareEvent(turn_id="b" * 32, preparation_id="a" * 32)
    assert parse_chat_event(event.model_dump_json()) == event
