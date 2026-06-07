# L1 module reorganization — platform / features split

`kumi/core/` was reorganized from a mixed by-layer/by-feature layout into a
deliberate hybrid:

- `kumi/core/platform/` — cross-cutting infrastructure (no feature knowledge)
- `kumi/core/features/<feature>/` — self-contained business capabilities, each
  owning its router + service + domain
- `kumi/core/api/` — the HTTP composition root (app assembly), which may import
  both platform and features

Dependency rule: **features depend on platform, never the reverse; features do
not import each other except through platform; `api` (composition) may import
both.** Verified: `platform/` and `features/` no longer import `kumi.core.api`,
and `platform/` has no import-time dependency on `features/`.

## Compatibility shims (deprecated)

Every moved module/package left a thin re-export shim at its **old** import path
so existing consumers keep working. The shims are **deprecated** and will be
removed in a future release. L1's own source and tests no longer use them —
they exist only for downstream consumers (notably `kumi-enterprise` /
`kumi-nexus`), which still import several old paths and should migrate using the
map below before the shims are deleted.

## Old → new import map

| Old path | New path |
|---|---|
| `kumi.core.tool` | `kumi.core.platform.tools.tool` |
| `kumi.core.tool_routing` | `kumi.core.platform.tools.tool_routing` |
| `kumi.core.tool_call_normalize` | `kumi.core.platform.tools.tool_call_normalize` |
| `kumi.core.tool_trace` | `kumi.core.platform.tools.tool_trace` |
| `kumi.core.auth` | `kumi.core.platform.security.auth` |
| `kumi.core.audit` | `kumi.core.platform.security.audit` |
| `kumi.core.connection` | `kumi.core.platform.security.connection` |
| `kumi.core.http_config` | `kumi.core.platform.security.http_config` |
| `kumi.core.exceptions` | `kumi.core.platform.exceptions` |
| `kumi.core.env_load` | `kumi.core.platform.env_load` |
| `kumi.core.runtime` | `kumi.core.platform.runtime` |
| `kumi.core.providers` | `kumi.core.platform.providers` |
| `kumi.core.streaming` | `kumi.core.platform.streaming` |
| `kumi.core.plugins` | `kumi.core.platform.plugins` |
| `kumi.core.dispatch` | `kumi.core.platform.dispatch` |
| `kumi.core.memories` | `kumi.core.features.memory` |
| `kumi.core.proactive` | `kumi.core.features.proactive` |
| `kumi.core.stt` | `kumi.core.features.stt` |
| `kumi.core.multimodal` | `kumi.core.features.uploads.multimodal` |
| `kumi.core.config` | `kumi.core.features.config` |
| `kumi.core.prompts` | `kumi.core.features.prompts` |
| `kumi.core.services.chat_turn` | `kumi.core.features.chat.service` |
| `kumi.tools.timer_tools` | `kumi.core.features.proactive.timer_tools` |
| `kumi.core.api.events` | `kumi.core.platform.http.events` |
| `kumi.core.api.dependencies` | `kumi.core.platform.http.dependencies` |
| `kumi.core.api.schemas` | `kumi.core.platform.http.schemas` |
| `kumi.core.api.http_errors` | `kumi.core.platform.http.http_errors` |
| `kumi.core.api.task_logging` | `kumi.core.platform.http.task_logging` |
| `kumi.core.api.docs_middleware` | `kumi.core.platform.http.docs_middleware` |
| `kumi.core.api.stream_consumer` | `kumi.core.platform.http.stream_consumer` |
| `kumi.core.api.routers.<x>` | `kumi.core.features.<x>.router` |
| `kumi.core.api.chat` | `kumi.core.features.chat.pipeline` |
| `kumi.core.api.chat_context` | `kumi.core.features.chat.context` |
| `kumi.core.api.chat_debug_trace` | `kumi.core.features.chat.debug_trace` |
| `kumi.core.api.uploads` | `kumi.core.features.uploads.service` |
| `kumi.core.api.timers` | `kumi.core.features.proactive.scheduler` |
| `kumi.core.api.edge` | `kumi.core.features.edge.api` |
| `kumi.core.api.peers` | `kumi.core.features.edge.peers` |
| `kumi.core.api.state` (accessors) | `kumi.core.platform.runtime.accessors` |
| `kumi.core.api.state.get_memory_store[_for_identity]` | `kumi.core.features.memory.store` |

Unchanged: `kumi.core.chatbot`, `kumi.core.api.app_factory`,
`kumi.core.api` (`app` / `create_app`), `kumi.core.api.__main__`
(`python -m kumi.core.api`).
