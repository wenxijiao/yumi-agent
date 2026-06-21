"""Providers must emit `usage` before `tool_call`.

The chat consumers stop the stream on the tool_call signal, so a usage chunk
yielded after it is dropped — under-counting quota/cost on tool-call turns.
Ollama is the representative case here (its stream is plain dicts, easy to
fake); the other providers follow the same reordered contract.
"""

import asyncio

import yumi.core.platform.providers.ollama_provider as ollama_mod
from yumi.core.platform.providers.ollama_provider import OllamaProvider


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def chat(self, **kwargs):  # noqa: ARG002
        return _FakeStream(self._chunks)


class _FakeOllama:
    def __init__(self, chunks):
        self._chunks = chunks

    def AsyncClient(self):
        return _FakeClient(self._chunks)


async def _collect(agen):
    return [c async for c in agen]


def test_ollama_emits_usage_before_tool_call(monkeypatch):
    chunk = {
        "message": {"tool_calls": [{"id": "c0", "function": {"name": "do_it", "arguments": {}}}]},
        "prompt_eval_count": 11,
        "eval_count": 5,
    }
    monkeypatch.setattr(ollama_mod, "ollama", _FakeOllama([chunk]))

    out = asyncio.run(_collect(OllamaProvider().chat_stream(model="m", messages=[])))
    types = [c["type"] for c in out]

    assert "usage" in types, f"no usage chunk in {types}"
    assert "tool_call" in types, f"no tool_call chunk in {types}"
    assert types.index("usage") < types.index("tool_call")
