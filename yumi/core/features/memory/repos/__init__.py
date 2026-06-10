"""Per-table repositories owned by :class:`yumi.core.features.memory.memory.Memory`.

Each repository:

* owns one LanceDB table (schema, init, migration, CRUD),
* shares the :class:`~yumi.core.features.memory.backend.LanceDBBackend` so table
  helpers and time/SQL primitives are not duplicated,
* exposes a small public API the :class:`Memory` façade delegates to.

The split exists so deployments can swap LanceDB for another store by
implementing the same repository surface without rewriting the façade.
"""

from yumi.core.features.memory.repos.long_term import LongTermMemoryRepository
from yumi.core.features.memory.repos.messages import MessageRepository
from yumi.core.features.memory.repos.observations import ToolObservationRepository
from yumi.core.features.memory.repos.sessions import SessionRepository
from yumi.core.features.memory.repos.summaries import SessionSummaryRepository

__all__ = [
    "LongTermMemoryRepository",
    "MessageRepository",
    "SessionRepository",
    "SessionSummaryRepository",
    "ToolObservationRepository",
]
