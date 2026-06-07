"""Per-table repositories owned by :class:`kumi.core.features.memory.memory.Memory`.

Each repository:

* owns one LanceDB table (schema, init, migration, CRUD),
* shares the :class:`~kumi.core.features.memory.backend.LanceDBBackend` so table
  helpers and time/SQL primitives are not duplicated,
* exposes a small public API the :class:`Memory` façade delegates to.

The split exists so enterprise builds can swap LanceDB for another store
(e.g. PostgreSQL via ``kumi_enterprise.tenancy.postgres_store``) by
implementing the same Repository surface without rewriting the façade.
"""

from kumi.core.features.memory.repos.long_term import LongTermMemoryRepository
from kumi.core.features.memory.repos.messages import MessageRepository
from kumi.core.features.memory.repos.observations import ToolObservationRepository
from kumi.core.features.memory.repos.sessions import SessionRepository
from kumi.core.features.memory.repos.summaries import SessionSummaryRepository

__all__ = [
    "LongTermMemoryRepository",
    "MessageRepository",
    "SessionRepository",
    "SessionSummaryRepository",
    "ToolObservationRepository",
]
