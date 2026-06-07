# L1 module reorganization — platform / features split

`yumi/core/` was reorganized from a mixed by-layer/by-feature layout into a
deliberate hybrid:

- `yumi/core/platform/` — cross-cutting infrastructure (no feature knowledge)
- `yumi/core/features/<feature>/` — self-contained business capabilities, each
  owning its router + service + domain
- `yumi/core/api/` — the HTTP composition root (app assembly), which may import
  both platform and features

Dependency rule: **features depend on platform, never the reverse; features do
not import each other except through platform; `api` (composition) may import
both.** Verified: `platform/` and `features/` no longer import `yumi.core.api`,
and `platform/` has no import-time dependency on `features/`.

## Compatibility shims (deprecated)

Every moved module/package left a thin re-export shim at its **old** import path
so existing consumers keep working. The shims are **deprecated** and will be
removed in a future release. L1's own source and tests no longer use them —
they exist only for downstream consumers (notably `yumi-enterprise` /
`yumi-nexus`), which still import several old paths and should migrate using the
map below before the shims are deleted.

## Old → new import map

| Old path | New path |
|---|---|
| `yumi.core.tool` | `yumi.core.platform.tools.tool` |
| `yumi.core.tool_routing` | `yumi.core.platform.tools.tool_routing` |
| `yumi.core.tool_call_normalize` | `yumi.core.platform.tools.tool_call_normalize` |
| `yumi.core.tool_trace` | `yumi.core.platform.tools.tool_trace` |
| `yumi.core.auth` | `yumi.core.platform.security.auth` |
| `yumi.core.audit` | `yumi.core.platform.security.audit` |
| `yumi.core.connection` | `yumi.core.platform.security.connection` |
| `yumi.core.http_config` | `yumi.core.platform.security.http_config` |
| `yumi.core.exceptions` | `yumi.core.platform.exceptions` |
| `yumi.core.env_load` | `yumi.core.platform.env_load` |
| `yumi.core.runtime` | `yumi.core.platform.runtime` |
| `yumi.core.providers` | `yumi.core.platform.providers` |
| `yumi.core.streaming` | `yumi.core.platform.streaming` |
| `yumi.core.plugins` | `yumi.core.platform.plugins` |
| `yumi.core.dispatch` | `yumi.core.platform.dispatch` |
| `yumi.core.memories` | `yumi.core.features.memory` |
| `yumi.core.proactive` | `yumi.core.features.proactive` |
| `yumi.core.stt` | `yumi.core.features.stt` |
| `yumi.core.multimodal` | `yumi.core.features.uploads.multimodal` |
| `yumi.core.config` | `yumi.core.features.config` |
| `yumi.core.prompts` | `yumi.core.features.prompts` |
| `yumi.core.services.chat_turn` | `yumi.core.features.chat.service` |
| `yumi.tools.timer_tools` | `yumi.core.features.proactive.timer_tools` |
| `yumi.core.api.events` | `yumi.core.platform.http.events` |
| `yumi.core.api.dependencies` | `yumi.core.platform.http.dependencies` |
| `yumi.core.api.schemas` | `yumi.core.platform.http.schemas` |
| `yumi.core.api.http_errors` | `yumi.core.platform.http.http_errors` |
| `yumi.core.api.task_logging` | `yumi.core.platform.http.task_logging` |
| `yumi.core.api.docs_middleware` | `yumi.core.platform.http.docs_middleware` |
| `yumi.core.api.stream_consumer` | `yumi.core.platform.http.stream_consumer` |
| `yumi.core.api.routers.<x>` | `yumi.core.features.<x>.router` |
| `yumi.core.api.chat` | `yumi.core.features.chat.pipeline` |
| `yumi.core.api.chat_context` | `yumi.core.features.chat.context` |
| `yumi.core.api.chat_debug_trace` | `yumi.core.features.chat.debug_trace` |
| `yumi.core.api.uploads` | `yumi.core.features.uploads.service` |
| `yumi.core.api.timers` | `yumi.core.features.proactive.scheduler` |
| `yumi.core.api.edge` | `yumi.core.features.edge.api` |
| `yumi.core.api.peers` | `yumi.core.features.edge.peers` |
| `yumi.core.api.state` (accessors) | `yumi.core.platform.runtime.accessors` |
| `yumi.core.api.state.get_memory_store[_for_identity]` | `yumi.core.features.memory.store` |

Unchanged: `yumi.core.chatbot`, `yumi.core.api.app_factory`,
`yumi.core.api` (`app` / `create_app`), `yumi.core.api.__main__`
(`python -m yumi.core.api`).
