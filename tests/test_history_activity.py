from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from yumi.core.features.assistant import router as assistant
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.plugins import Identity
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = AssistantStore(SQLiteStore(tmp_path / "history.db"), "alice")
    monkeypatch.setattr(assistant, "_store", lambda identity: store)

    def own(identity, row):
        if not row["session_id"].startswith("u_alice__"):
            raise HTTPException(403, "Not your message")

    monkeypatch.setattr(
        assistant,
        "get_session_scope",
        lambda: SimpleNamespace(
            ensure_message_owned_by_identity=own,
            session_id_prefix_for_identity=lambda identity: "u_alice__",
        ),
    )
    app = FastAPI()
    app.include_router(assistant.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    with TestClient(app) as client:
        yield store, client


def put(store, mid="answer", role="assistant", sid="u_alice__personal_1"):
    store.sqlite.upsert_event_from_message(
        {
            "id": mid,
            "session_id": sid,
            "role": role,
            "content": "The reply",
            "turn_id": "turn",
            "thought": "Saved thought",
        }
    )


def trace(store, sid="u_alice__personal_1"):
    store.sqlite.upsert_turn_trace(
        {
            "id": "turn",
            "session_id": sid,
            "system_prompt": "Do not expose this",
            "summary": {"tool_call_count": 1},
            "rounds": [
                {
                    "reasoning_text": "Reasoning before the call",
                    "tool_calls": [
                        {
                            "id": "call",
                            "function": {"name": "get_weather", "arguments": '{"city":"Auckland","password":"secret"}'},
                        }
                    ],
                    "tool_results": [
                        {
                            "call_id": "call",
                            "tool": "get_weather",
                            "status": "success",
                            "duration_ms": 25,
                            "result_preview": "Sunny",
                        }
                    ],
                },
                {"reasoning_text": "Reasoning after the call"},
            ],
        },
        owner_user_id="alice",
    )


def test_detail_recovers_reasoning_and_tools_without_model_inputs(env):
    store, client = env
    put(store)
    trace(store)
    result = client.get("/assistant/history/answer")
    assert result.status_code == 200
    body = result.json()
    assert body["thought"] == "Reasoning before the call\n\nReasoning after the call"
    assert body["content"] == "The reply"
    assert body["tool_calls"][0]["result"] == "Sunny"
    assert body["tool_calls"][0]["arguments"] == {"city": "Auckland", "password": "[redacted]"}
    assert "Do not expose" not in result.text
    assert client.get("/assistant/history").json()["messages"][0]["tool_call_count"] == 1


def test_user_messages_never_include_assistant_activity_and_missing_traces_stay_empty(env):
    store, client = env
    put(store, mid="question", role="user")
    trace(store)
    assert client.get("/assistant/history/question").json()["tool_calls"] == []
    assert client.get("/assistant/history").json()["messages"][0]["tool_call_count"] == 0
    put(store)
    store.sqlite.delete_turn_traces_for_session("u_alice__personal_1")
    body = client.get("/assistant/history/answer").json()
    assert body["thought"] == "Saved thought" and body["tool_calls"] == []
    assert body["activity_available"] is False


def test_activity_never_crosses_sessions_and_hidden_messages_are_rejected(env):
    store, client = env
    put(store)
    trace(store, sid="u_bob__personal_1")
    body = client.get("/assistant/history/answer").json()
    assert body["thought"] == "Saved thought" and body["tool_calls"] == []
    put(store, mid="other", sid="u_bob__personal_1")
    put(store, mid="group", sid="u_alice__group_1")
    assert client.get("/assistant/history/other").status_code == 403
    assert client.get("/assistant/history/group").status_code == 404
    store.sqlite.delete_message("answer")
    assert client.get("/assistant/history/answer").status_code == 404


def test_opening_another_session_preserves_activity_and_deleted_messages(tmp_path):
    from yumi.core.features.memory.memory import Memory

    sid = "u_alice__personal_1"
    memory = Memory(session_id=sid, storage_dir=tmp_path)
    answer = memory.add_message("assistant", "The reply", turn_id="turn")
    deleted = memory.add_message("user", "Removed from canonical history")
    # A stale vector row must not revive a deletion or overwrite the richer
    # canonical event when a new session/account-level Memory is opened.
    memory.sqlite.delete_message(deleted)
    store = AssistantStore(memory.sqlite, "alice")
    trace(store)
    before = memory.sqlite.get_message(answer)

    reopened = Memory(session_id="default", storage_dir=tmp_path)
    after = reopened.sqlite.get_message(answer)
    assert after == before
    assert reopened.sqlite.get_message(deleted) is None
    detail = AssistantStore(reopened.sqlite, "alice").message_detail(after)
    assert detail["thought"] == "Reasoning before the call\n\nReasoning after the call"
    assert detail["tool_calls"][0]["result"] == "Sunny"


def test_round_activity_keeps_intermediate_output_failed_call_and_retry(env):
    store, client = env
    put(store)
    trace(store)
    record = store.sqlite.get_turn_trace("turn")
    record["rounds"][0].update(
        index=1,
        response_text="I will try the weather tool.",
        finish={"reason": "tool_calls"},
        usage={"prompt_tokens": 10, "completion_tokens": 3},
    )
    record["rounds"][0]["tool_results"][0].update(status="error", result_preview="Temporary failure")
    record["rounds"][1].update(
        index=2,
        response_text="I can try another source.",
        finish={"reason": "retry"},
        tool_calls=[{"function": "invalid"}],
    )
    record["rounds"].append({"index": 3, "response_text": "It is sunny.", "finish": {"reason": "stop"}})
    record["timeline"] = [
        {"round": 2, "kind": "tool_status", "status": "error", "label": "Invalid parameters; retrying."}
    ]
    store.sqlite.upsert_turn_trace(record, owner_user_id="alice")
    result = client.get("/assistant/history/answer")
    rounds = result.json()["rounds"]
    assert [r["response_text"] for r in rounds] == [
        "I will try the weather tool.",
        "I can try another source.",
        "It is sunny.",
    ]
    assert rounds[0]["tool_calls"][0]["status"] == "error"
    assert rounds[0]["tool_calls"][0]["arguments"]["password"] == "[redacted]"
    assert rounds[1]["finish_reason"] == "retry"
    assert rounds[1]["events"][0]["status"] == "error"
    assert "Do not expose" not in result.text
