from __future__ import annotations

from yumi.core.features.memory.embedding_runner import EmbeddingProcessor


def test_embedding_generation_failure_does_not_permanently_disable_embeddings():
    class _FlakyProvider:
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, model: str, text: str) -> list[float]:  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary outage")
            return [1.0, 2.0, 3.0]

    processor = EmbeddingProcessor.__new__(EmbeddingProcessor)
    processor.embed_model = "test-embed"
    processor.embed_provider = _FlakyProvider()
    processor.fallback_vector_size = 3
    processor.embedding_available = True

    assert processor.get_vector("first") == [0.0, 0.0, 0.0]
    assert processor.embedding_available is True
    assert processor.get_vector("second") == [1.0, 2.0, 3.0]
