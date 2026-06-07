"""Embedding lifecycle: availability check, dim migration, background re-embed.

Pulled out of the legacy ``Memory`` god class so the message-repository
layer can stay focused on CRUD. The processor is shared by every repo
that vectorises content (messages, long-term memories, tool observations,
session summaries).

Threading model
---------------
Dimension migration runs synchronously during :meth:`maybe_migrate` (cheap;
just a vector-shape comparison + drop/recreate of the message table).
Re-embedding the body of every row runs on a background daemon thread so
``Memory(...)`` returns promptly. While the background sweep is in flight,
``embedding_available`` is False so newly inserted rows are stored with
zero-vectors and picked up by the sweep's incremental phase.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import lancedb
from kumi.core.features.config import load_model_config, save_model_config
from kumi.core.features.memory.backend import LanceDBBackend
from kumi.core.features.memory.embedding_state import is_degenerate_vector as _is_degenerate_vector
from kumi.logging_config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class EmbeddingProcessor:
    """Owns the embedding state for one Memory instance.

    Holds the active provider + model name, tracks whether the embedding
    pipeline is healthy, and manages dimension migration when the user
    changes embedding models. ``get_vector(text)`` is the single entry
    point repos use to vectorise content.
    """

    def __init__(self, backend: LanceDBBackend, embed_model: str | None, embed_provider: Any | None) -> None:
        self.backend = backend
        self.embed_model = embed_model
        self.embed_provider = embed_provider
        self.fallback_vector_size = 1024
        self.embedding_available = self._check_availability()

    # ── availability ───────────────────────────────────────────────────────

    def _check_availability(self) -> bool:
        if not self.embed_model or self.embed_provider is None:
            return False
        config = load_model_config()
        if config.embedding_provider == "ollama":
            from kumi.core.assets_check import assets_check

            return assets_check()
        return True

    # ── vectorisation ──────────────────────────────────────────────────────

    def get_vector(self, text: str) -> list[float]:
        """Return an embedding vector for ``text`` (zero-filled fallback on failure)."""
        if not self.embed_model or not self.embedding_available or self.embed_provider is None:
            return [0.0] * self.fallback_vector_size
        try:
            return self.embed_provider.embed(self.embed_model, text)
        except Exception as exc:
            logger.warning("Embedding generation failed: %s", exc)
            self.embedding_available = False
            return [0.0] * self.fallback_vector_size

    def normalise_vector(self, vector, content: str) -> list[float]:
        """Coerce arbitrary vector input into a Python list, embedding when missing."""
        if vector is None:
            return self.get_vector(content)
        if hasattr(vector, "tolist"):
            return vector.tolist()
        return list(vector)

    @staticmethod
    def is_degenerate(vector) -> bool:
        return _is_degenerate_vector(vector)

    # ── dimension migration / re-embed ─────────────────────────────────────

    def maybe_migrate(self, message_table_name: str) -> None:
        """Detect a vector-dim mismatch and trigger a rebuild + background sweep."""
        if not self.embedding_available or not self.embed_model:
            return
        if not self.backend.has_table(message_table_name):
            return

        table = self.backend.open_table(message_table_name)
        rows = table.search(query=None, ordering_field_name="timestamp_num").limit(1).to_list()
        if not rows:
            return

        existing_vec = rows[0].get("vector")
        if existing_vec is None:
            return
        if hasattr(existing_vec, "tolist"):
            existing_vec = existing_vec.tolist()
        existing_dim = len(existing_vec)

        try:
            test_vec = self.embed_provider.embed(self.embed_model, "dimension test")
            new_dim = len(test_vec)
        except Exception:
            return

        if existing_dim == new_dim:
            if all(v == 0.0 for v in existing_vec):
                logger.info(
                    "Detected incomplete migration (zero-vectors with dim=%s). Resuming background re-embed.",
                    new_dim,
                )
                self.fallback_vector_size = new_dim
                self.embedding_available = False
                self._spawn_re_embed(message_table_name, new_dim)
                return
            config = load_model_config()
            if config.embedding_dim != new_dim:
                config.embedding_dim = new_dim
                save_model_config(config)
            return

        self.fallback_vector_size = new_dim
        logger.info(
            "Embedding dimension changed (%s -> %s). Rebuilding vectors in background.",
            existing_dim,
            new_dim,
        )
        self._rebuild_with_zero_vectors(message_table_name, new_dim)
        config = load_model_config()
        config.embedding_dim = new_dim
        save_model_config(config)
        self._spawn_re_embed(message_table_name, new_dim)

    def _rebuild_with_zero_vectors(self, table_name: str, dim: int) -> None:
        if not self.backend.has_table(table_name):
            return

        table = self.backend.open_table(table_name)
        all_rows = table.to_pandas().to_dict(orient="records")
        zero_vec = [0.0] * dim

        rebuilt = []
        for row in all_rows:
            rebuilt.append(
                {
                    "id": row["id"],
                    "vector": zero_vec,
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "thought": str(row.get("thought") or ""),
                    "timestamp": row["timestamp"],
                    "timestamp_num": int(row["timestamp_num"]),
                }
            )
        self.backend.db.drop_table(table_name, ignore_missing=True)
        if rebuilt:
            self.backend.db.create_table(table_name, data=rebuilt)
        self.embedding_available = False

    def _spawn_re_embed(self, table_name: str, dim: int) -> None:
        thread = threading.Thread(
            target=self._background_re_embed,
            args=(table_name, dim),
            name="kumi-reembed",
            daemon=True,
        )
        thread.start()

    def _background_re_embed(self, table_name: str, dim: int) -> None:
        """Re-embed every row in the message table on a daemon thread.

        Uses LanceDB's ``update`` API to modify vectors in-place — per-row
        delete+add would explode fragment count on a columnar store. After
        the main pass, an incremental sweep catches messages inserted while
        the rebuild was running. A compaction pass consolidates versions.
        """
        try:
            task_start_ts = LanceDBBackend.current_timestamp_num()

            db = lancedb.connect(self.backend.db_dir)
            if not self.backend.has_table(table_name, db):
                return

            table = db.open_table(table_name)
            all_rows = table.to_pandas().to_dict(orient="records")
            snapshot_ids = {row["id"] for row in all_rows}

            updated_count = 0
            skipped = 0
            for row in all_rows:
                vec = row.get("vector")
                if hasattr(vec, "tolist"):
                    vec = vec.tolist()
                if vec and any(v != 0.0 for v in vec):
                    skipped += 1
                    continue

                content = row.get("content", "") or ""
                row_id = row["id"]
                try:
                    vector = self.embed_provider.embed(self.embed_model, content)
                except Exception:
                    vector = [0.0] * dim

                try:
                    table.update(
                        where=f"id = '{LanceDBBackend.escape_where_value(row_id)}'",
                        values={"vector": vector},
                    )
                    updated_count += 1
                except Exception as row_exc:
                    logger.warning("Failed to re-embed row %s: %s", row_id, row_exc)

            try:
                table = db.open_table(table_name)
                new_rows = (
                    table.search(query=None, ordering_field_name="timestamp_num")
                    .where(f"timestamp_num >= {task_start_ts}")
                    .to_list()
                )
                sweep_count = 0
                for row in new_rows:
                    if row["id"] in snapshot_ids:
                        continue
                    vec = row.get("vector")
                    if vec is not None and hasattr(vec, "tolist"):
                        vec = vec.tolist()
                    if vec and any(v != 0.0 for v in vec):
                        continue
                    content = row.get("content", "") or ""
                    try:
                        vector = self.embed_provider.embed(self.embed_model, content)
                        table.update(
                            where=f"id = '{LanceDBBackend.escape_where_value(row['id'])}'",
                            values={"vector": vector},
                        )
                        sweep_count += 1
                    except Exception as sweep_row_exc:
                        logger.debug("Incremental sweep row skip: %s", sweep_row_exc)
                if sweep_count:
                    logger.info("Incremental sweep: re-embedded %s new message(s).", sweep_count)
            except Exception as sweep_exc:
                logger.warning("Incremental sweep failed (non-fatal): %s", sweep_exc)

            try:
                table.compact_files()
                table.cleanup_old_versions()
            except Exception as compact_exc:
                logger.warning("Post-reembed compaction failed (non-fatal): %s", compact_exc)

            self.embedding_available = True
            msg = f"[Memory] Re-embedding complete. {updated_count} updated"
            if skipped:
                msg += f", {skipped} skipped (already valid)"
            logger.info("%s.", msg)

        except Exception:
            logger.exception("Background re-embedding failed")


__all__ = ["EmbeddingProcessor"]
