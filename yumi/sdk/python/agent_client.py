"""Yumi Edge SDK — self-contained Python agent client.

Only external dependency: ``websockets`` (``pip install websockets``).
All auth, connection, and tool-schema logic is inlined so this file
can be dropped into any project without the full ``yumi`` package.
"""

import asyncio
import base64
import copy
import inspect
import json
import logging
import os
import random
import re
import socket
import threading
import types
import typing
import urllib.error
import urllib.request
from typing import Any, Callable, get_args, get_origin
from urllib.parse import urlparse

import websockets

_LOG = logging.getLogger("yumi.sdk")

_TOOL_CONFIRMATION_FILENAME = ".yumi_tool_confirmation.json"


def _reconnect_delay_sec_with_jitter(delay_sec: int) -> float:
    """Seconds to wait before reconnect, with ±500ms jitter (thundering herd mitigation)."""
    base_ms = delay_sec * 1000
    jitter = random.randint(-500, 500)
    return max(1.0, (base_ms + jitter) / 1000.0)


# ── auth constants ──

_TOKEN_PREFIX = "yumi_"
_LAN_TOKEN_PREFIX = "yumi-lan_"
_LEGACY_LAN_PREFIXES = ("ml1_", "yumi_lan_")

# ── base64url helpers ──


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ── LAN code / credential decode ──


def _decode_lan_code(token: str) -> tuple[str, int]:
    """Decode a ``yumi-lan_`` token → ``(host, port)``."""
    if token.startswith(_LAN_TOKEN_PREFIX):
        encoded = token[len(_LAN_TOKEN_PREFIX) :]
    else:
        matched = False
        for prefix in _LEGACY_LAN_PREFIXES:
            if token.startswith(prefix):
                encoded = token[len(prefix) :]
                matched = True
                break
        if not matched:
            raise ValueError("Invalid Yumi LAN code prefix.")

    data = json.loads(_b64url_decode(encoded))

    if "h" in data:
        host = str(data["h"])
        port = int(data.get("p", 8000))
    elif "base_url" in data:
        parsed = urlparse(data["base_url"])
        if not parsed.hostname:
            raise ValueError("LAN code missing host.")
        host = parsed.hostname
        port = parsed.port or 8000
    else:
        raise ValueError("LAN code missing host.")

    import time

    if data.get("x", 0) and int(data["x"]) < int(time.time()):
        raise ValueError("LAN code has expired.")

    return host, port


def _decode_credential(token: str) -> dict:
    """Decode a ``yumi_`` credential token → dict with at least ``relay_url``."""
    if not token.startswith(_TOKEN_PREFIX):
        raise ValueError("Invalid Yumi credential prefix.")
    return json.loads(_b64url_decode(token[len(_TOKEN_PREFIX) :]))


# ── connection helpers ──


def _http_to_ws(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


def _parse_lan_code(code: str) -> str:
    """LAN code → ``http://host:port``."""
    host, port = _decode_lan_code(code)
    return f"http://{host}:{port}"


def _bootstrap_profile(join_code: str, scope: str, device_name: str = "") -> dict:
    """POST to relay ``/v1/bootstrap`` and return ``{"relay_url", "access_token"}``."""
    cred = _decode_credential(join_code)
    relay_url = cred["relay_url"].rstrip("/")

    payload = json.dumps(
        {
            "join_code": join_code,
            "scope": scope,
            "device_name": device_name.strip(),
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{relay_url}/v1/bootstrap",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Bootstrap failed: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Bootstrap failed: {exc.reason}") from exc

    at = data.get("access_token")
    if not isinstance(at, str) or not at:
        raise ValueError("Bootstrap response missing access_token.")

    return {"relay_url": relay_url, "access_token": at}


class _ConnectionConfig:
    __slots__ = ("mode", "base_url", "access_token")

    def __init__(self, *, mode: str, base_url: str, access_token: str | None = None):
        self.mode = mode
        self.base_url = base_url
        self.access_token = access_token

    def relay_edge_ws_url(self) -> str:
        return _http_to_ws(self.base_url.rstrip("/")) + "/ws/edge"


# ── type-annotation → JSON schema ──


_STR_TYPE_MAP: dict[str, dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "list": {"type": "array", "items": {"type": "string"}},
    "tuple": {"type": "array", "items": {"type": "string"}},
    "set": {"type": "array", "items": {"type": "string"}},
    "dict": {"type": "object", "additionalProperties": {"type": "string"}},
}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    if annotation == inspect.Parameter.empty:
        return {"type": "string"}
    if isinstance(annotation, str):
        return _STR_TYPE_MAP.get(annotation, {"type": "string"})

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is not None:
        if origin in (list, tuple, set):
            item_schema = _annotation_to_schema(args[0]) if args else {"type": "string"}
            return {"type": "array", "items": item_schema}
        if origin is dict:
            value_schema = _annotation_to_schema(args[1]) if len(args) > 1 else {"type": "string"}
            return {"type": "object", "additionalProperties": value_schema}
        if origin in (types.UnionType, typing.Union):
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _annotation_to_schema(non_none[0])
            return {"type": "string"}

    simple_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in simple_map:
        return {"type": simple_map[annotation]}
    if annotation in (list, tuple, set):
        return {"type": "array", "items": {"type": "string"}}
    if annotation is dict:
        return {"type": "object", "additionalProperties": {"type": "string"}}

    return {"type": "string"}


# ── .env parser (replaces python-dotenv) ──


def _load_env_file(path: str) -> None:
    """Parse a simple key=value .env file into os.environ."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except OSError:
        pass


def _find_env_file(start_dir: str) -> str:
    """Walk up from ``start_dir`` for ``yumi_tools/.env`` (preferred) or a bare ``.env``.

    Lets an edge find its config no matter which subdir it is launched from (e.g.
    cwd = ``<workspace>/yumi_tools/python`` while ``.env`` lives at
    ``<workspace>/yumi_tools/.env``). Falls back to ``<start_dir>/.env`` when
    nothing is found, so ``_policy_base_dir`` stays stable.
    """
    directory = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(directory, "yumi_tools", ".env")
        if os.path.isfile(candidate):
            return candidate
        bare = os.path.join(directory, ".env")
        if os.path.isfile(bare):
            return bare
        parent = os.path.dirname(directory)
        if parent == directory:
            return os.path.join(os.path.abspath(start_dir), ".env")
        directory = parent


# ── tool schema builder ──


def _wire_tool_schema(tool_entry: dict) -> dict:
    """Build the JSON tool object sent on edge WebSocket register."""
    sch = copy.deepcopy(tool_entry["schema"])
    if tool_entry.get("require_confirmation"):
        sch["require_confirmation"] = True
    if tool_entry.get("always_include"):
        sch["always_include"] = True
    if tool_entry.get("allow_proactive"):
        sch["allow_proactive"] = True
    if tool_entry.get("proactive_context"):
        sch["proactive_context"] = True
    if tool_entry.get("proactive_context_args") is not None:
        sch["proactive_context_args"] = tool_entry.get("proactive_context_args")
    if tool_entry.get("proactive_context_description"):
        sch["proactive_context_description"] = tool_entry.get("proactive_context_description")
    return sch


_ARGS_SECTION_RE = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.MULTILINE)
_ARG_LINE_RE = re.compile(r"^\s{4,}(\w+)\s*(?:\(.*?\))?\s*:\s*(.+)")
_RETURNS_SECTION_RE = re.compile(r"^\s*(Returns?|Yields?)\s*:\s*$", re.MULTILINE)


def _parse_docstring(func: Callable) -> tuple[str, dict[str, str], str | None]:
    """Extract description, param descriptions, and return doc from a Google-style docstring."""
    raw = inspect.getdoc(func) or ""
    if not raw:
        return "", {}, None

    args_match = _ARGS_SECTION_RE.search(raw)
    returns_match = _RETURNS_SECTION_RE.search(raw)

    if args_match:
        description = raw[: args_match.start()].strip()
    elif returns_match:
        description = raw[: returns_match.start()].strip()
    else:
        description = raw.strip()

    params: dict[str, str] = {}
    if args_match:
        end = returns_match.start() if returns_match and returns_match.start() > args_match.end() else len(raw)
        args_block = raw[args_match.end() : end]
        for line in args_block.splitlines():
            m = _ARG_LINE_RE.match(line)
            if m:
                params[m.group(1)] = m.group(2).strip()

    returns_doc: str | None = None
    if returns_match:
        returns_block = raw[returns_match.end() :]
        returns_doc = returns_block.strip().split("\n")[0].strip() or None

    return description, params, returns_doc


def _build_tool_schema(
    func: Callable,
    name: str | None = None,
    description: str | None = None,
    params: dict[str, str] | None = None,
    returns: str | None = None,
) -> dict:
    doc_desc, doc_params, doc_returns = _parse_docstring(func)

    resolved_name = name or func.__name__
    resolved_desc = description or doc_desc or resolved_name
    resolved_params = params if params is not None else doc_params
    resolved_returns = returns or doc_returns

    full_description = resolved_desc
    if resolved_returns:
        full_description += f"\nReturns: {resolved_returns}"

    sig = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}
    properties: dict[str, Any] = {}
    required_params: list[str] = []

    for param_name, param in sig.parameters.items():
        if param.default == inspect.Parameter.empty:
            required_params.append(param_name)

        annotation = hints.get(param_name, param.annotation)
        param_schema = _annotation_to_schema(annotation)
        if resolved_params and param_name in resolved_params:
            param_schema["description"] = resolved_params[param_name]
        else:
            param_schema["description"] = param_name
        properties[param_name] = param_schema

    return {
        "type": "function",
        "function": {
            "name": resolved_name,
            "description": full_description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required_params,
            },
        },
    }


# ══════════════════════════════════════════════════════════════
#  YumiAgent — public class
# ══════════════════════════════════════════════════════════════


class YumiAgent:
    """Embeddable Yumi edge client.

    Args:
        connection_code: Server connection code (LAN code, relay token,
            or WebSocket URL).  Falls back to ``YUMI_CONNECTION_CODE``
            / ``BRAIN_URL`` env vars, then ``yumi_tools/.env``.
        edge_name: Human-readable name shown in the server UI.
            Falls back to ``EDGE_NAME`` env var, then the hostname.
        env_path: Explicit path to a ``.env`` file.

    Usage::

        from yumi_sdk import YumiAgent

        agent = YumiAgent(
            connection_code="yumi-lan_...",
            edge_name="My Raspberry Pi",
        )
        agent.register(jump, "Make the character jump")
        agent.register(
            launch_missile,
            "Launch a missile",
            require_confirmation=True,
        )
        agent.run_in_background()
    """

    def __init__(
        self,
        connection_code: str | None = None,
        edge_name: str | None = None,
        env_path: str | None = None,
        *,
        on_error: Callable[[Exception], None] | None = None,
    ):
        if env_path:
            env_file = env_path
        else:
            env_file = _find_env_file(os.getcwd())

        _load_env_file(env_file)

        self._policy_base_dir = os.path.dirname(os.path.abspath(env_file))

        self._connection_code = connection_code or os.getenv("YUMI_CONNECTION_CODE") or os.getenv("BRAIN_URL")
        self._edge_name = edge_name or os.getenv("EDGE_NAME") or socket.gethostname()
        # Optional explicit edge server (host of a remote /ws/edge). When set, the
        # connection code is forwarded VERBATIM in register as an opaque credential
        # the server resolves — the client never interprets it. Keeps this SDK
        # generic across deployments (no hardcoded host / code format).
        self._edge_server = os.getenv("YUMI_EDGE_SERVER")

        self._tools: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[str, asyncio.Task] = {}
        self._on_error = on_error
        self._connected = False
        # Bootstrapped relay credentials are cached on the instance (not in
        # os.environ) so two agents in the same process never see each other's.
        self._relay_url: str | None = None
        self._relay_access_token: str | None = None
        self._register_connection_code: str | None = None

    def _confirmation_policy_path(self) -> str:
        override = (os.getenv("YUMI_TOOL_CONFIRMATION_PATH") or "").strip()
        if override:
            return os.path.expanduser(override)
        return os.path.join(self._policy_base_dir, _TOOL_CONFIRMATION_FILENAME)

    def _load_confirmation_policy(self) -> dict[str, list[str]]:
        path = self._confirmation_policy_path()
        if not os.path.isfile(path):
            return {"always_allow": [], "force_confirm": []}
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError, TypeError):
            return {"always_allow": [], "force_confirm": []}
        aa = raw.get("always_allow") or []
        fc = raw.get("force_confirm") or []
        if not isinstance(aa, list):
            aa = []
        if not isinstance(fc, list):
            fc = []
        return {
            "always_allow": [str(x) for x in aa if x],
            "force_confirm": [str(x) for x in fc if x],
        }

    def _save_confirmation_policy(self, data: dict[str, list[str]]) -> None:
        path = self._confirmation_policy_path()
        base = os.path.dirname(os.path.abspath(path))
        if base:
            os.makedirs(base, exist_ok=True)
        payload = {
            "always_allow": list(data.get("always_allow", [])),
            "force_confirm": list(data.get("force_confirm", [])),
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # ── public API ──

    @property
    def is_connected(self) -> bool:
        """True while the edge is connected to the server.

        Set by the background client, so it's meaningful after
        :meth:`run_in_background`. Lets embedders detect connection state
        instead of guessing from the absence of a return value.
        """
        return self._connected

    def _emit_error(self, exc: Exception) -> None:
        """Forward a connection error to the optional ``on_error`` callback."""
        if self._on_error is None:
            return
        try:
            self._on_error(exc)
        except Exception:
            _LOG.exception("on_error callback raised")

    def register(
        self,
        func: Callable,
        description: str,
        *,
        name: str | None = None,
        params: dict[str, str] | None = None,
        returns: str | None = None,
        timeout: int | None = None,
        require_confirmation: bool = False,
        mode: str = "dynamic",
        context_args: dict[str, Any] | None = None,
        context_label: str | None = None,
        allow_proactive: bool = False,
        # Deprecated low-level flags (prefer `mode`); still honored for back-compat.
        always_include: bool = False,
        proactive_context: bool = False,
        proactive_context_args: dict[str, Any] | None = None,
        proactive_context_description: str | None = None,
    ) -> None:
        """Register a tool function.

        ``description`` is the AI-facing instruction that tells the LLM
        when and how to use this tool.  It is always required so the
        experience is consistent across all language SDKs.

        Tool name defaults to ``func.__name__`` (override with *name*).
        Parameter types are extracted from type hints.  Parameter
        descriptions are extracted from the docstring ``Args:`` section,
        or can be overridden via *params*.

        **Human-in-the-loop:** Set ``require_confirmation=True`` for
        tools with irreversible side effects. The **server** asks the user
        in the web UI or in ``yumi --chat`` (not on the edge device).

        **Exposure mode** (``mode=``, pick one per tool):

        * ``"dynamic"`` (default) — the tool joins dynamic top-K retrieval; the
          model sees it only when it's relevant to the turn.
        * ``"pinned"`` — the tool's schema is exposed to the model every turn
          (skips retrieval). For a few high-value tools.
        * ``"autorun"`` — the tool is NOT offered to the model; instead it is run
          automatically before every reply and its result is injected as context
          for that turn only (never saved to history). Use it for ambient state
          the agent should always know — e.g. an edge ``get_user_context()``
          returning the user's recent mood/plans. Pass fixed arguments via
          ``context_args`` and a label via ``context_label`` (an ``autorun`` tool
          must be callable with no other required args).

        **Cancellation behaviour:** When the server cancels an in-flight
        tool call (timeout, user disconnect, or reconnect), the running
        ``asyncio.Task`` is cancelled.  For ``async def`` tools this
        raises ``CancelledError`` at the next ``await`` and stops
        execution immediately.  For *synchronous* (``def``) tools the
        underlying thread **cannot** be interrupted by Python — the
        function will run to completion even after cancellation is
        signalled.  If your tool performs long-running or side-effectful
        work, prefer ``async def`` with periodic ``await`` points so
        that cancellation takes effect promptly.

        Args:
            func: The callable to execute when the tool is invoked.
            description: What this tool does (shown to the LLM).
            name: Override the tool name (defaults to func.__name__).
            params: Override parameter descriptions.
            returns: Override the return value description.
            timeout: Per-tool execution timeout in seconds.  The server
                uses this instead of the global default when calling this tool.
            require_confirmation: If True, the user must approve in the
                Yumi UI or terminal chat before the server invokes this tool
                on the edge.
            mode: Exposure mode — "dynamic" (default), "pinned", or "autorun"
                (see above).
            context_args: Fixed arguments for a ``mode="autorun"`` tool.
            context_label: Label shown when a ``mode="autorun"`` result is
                injected (defaults to the tool name).
            allow_proactive: If True, this read-only tool may be used by
                proactive messaging. Defaults to False.
            always_include: Deprecated — use ``mode="pinned"``.
            proactive_context: Deprecated — use ``mode="autorun"``.
            proactive_context_args: Deprecated — use ``context_args``.
            proactive_context_description: Deprecated — use ``context_label``.
        """
        # Map the `mode` API onto the existing wire flags (one mode per tool).
        if mode == "pinned":
            always_include = True
        elif mode == "autorun":
            proactive_context = True
            if context_args is not None:
                proactive_context_args = context_args
            if context_label is not None:
                proactive_context_description = context_label
        elif mode != "dynamic":
            raise ValueError(f"mode must be 'dynamic', 'pinned', or 'autorun'; got {mode!r}")

        schema = _build_tool_schema(func, name, description, params, returns)
        if timeout is not None:
            schema["timeout"] = timeout
        tool_name = schema["function"]["name"]
        if not tool_name or not str(tool_name).strip():
            raise ValueError("Tool name cannot be empty; pass a non-empty name=.")
        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", str(tool_name)):
            raise ValueError(
                f"Tool name {tool_name!r} is invalid: use only letters, digits, '_' or '-' "
                "(max 64 chars). Model providers reject other function names."
            )
        if tool_name in self._tools:
            raise ValueError(f"A tool named {tool_name!r} is already registered; use a unique name= for each tool.")
        self._tools[tool_name] = {
            "schema": schema,
            "callable": func,
            "require_confirmation": require_confirmation,
            "always_include": always_include,
            "allow_proactive": allow_proactive,
            "proactive_context": proactive_context,
            "proactive_context_args": proactive_context_args,
            "proactive_context_description": proactive_context_description,
        }

    def run_in_background(
        self,
        *,
        connection_code: str | None = None,
        edge_name: str | None = None,
    ) -> None:
        """Start the edge client in a background daemon thread.

        Optional *connection_code* / *edge_name* override the values supplied at
        construction, applied just before the client starts. No-op if already
        running.
        """
        if self._thread is not None and self._thread.is_alive():
            return

        if connection_code is not None:
            self._connection_code = connection_code
        if edge_name is not None:
            self._edge_name = edge_name

        if not self._tools:
            _LOG.warning("No tools registered.")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._thread_entry,
            name="yumi-agent",
            daemon=True,
        )
        self._thread.start()

    def run(
        self,
        *,
        connection_code: str | None = None,
        edge_name: str | None = None,
    ) -> None:
        """Run in the FOREGROUND until interrupted (Ctrl+C) or stopped.

        Use this for a standalone edge script that *is* the process — it keeps
        the program alive so the edge stays connected. An embedded host (a GUI
        app, a game, another running service) should use
        :meth:`run_in_background`, which returns immediately and lets the host
        own the lifecycle.
        """
        self.run_in_background(connection_code=connection_code, edge_name=edge_name)
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully shut down the background client."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ── internals ──

    def _cancel_in_flight(self) -> None:
        """Cancel all in-flight tool tasks and clear the registry."""
        for task in self._in_flight.values():
            if not task.done():
                task.cancel()
        self._in_flight.clear()

    def _resolve_connection(self) -> _ConnectionConfig:
        # Cached from a prior bootstrap on THIS instance (no cross-agent leak).
        if self._relay_url and self._relay_access_token:
            return _ConnectionConfig(
                mode="relay",
                base_url=self._relay_url.rstrip("/"),
                access_token=self._relay_access_token,
            )

        # Explicit env config set by the user is still honored.
        relay_url = os.getenv("YUMI_RELAY_URL")
        access_token = os.getenv("YUMI_ACCESS_TOKEN")
        if relay_url and access_token:
            return _ConnectionConfig(
                mode="relay",
                base_url=relay_url.rstrip("/"),
                access_token=access_token,
            )

        # Explicit edge server + opaque connection code: connect straight to the
        # given server's /ws/edge and forward the code verbatim in register (the
        # server resolves it to the owning user). The client never interprets the
        # code, so this works for any deployment and sidesteps the yumi_ prefix clash.
        server = (self._edge_server or "").strip()
        if server:
            if server.startswith(("ws://", "wss://")):
                ws_url = server.rstrip("/")
            elif server.startswith(("http://", "https://")):
                ws_url = _http_to_ws(server.rstrip("/"))
            else:
                ws_url = "wss://" + server.rstrip("/")
            if not ws_url.endswith("/ws/edge"):
                ws_url = ws_url.rstrip("/") + "/ws/edge"
            self._register_connection_code = (self._connection_code or "").strip() or None
            return _ConnectionConfig(mode="direct", base_url=ws_url)

        code = self._connection_code or ""

        if code.startswith(("ws://", "wss://")):
            return _ConnectionConfig(mode="direct", base_url=code)

        if code.startswith(_LAN_TOKEN_PREFIX) or any(code.startswith(p) for p in _LEGACY_LAN_PREFIXES):
            server_url = _parse_lan_code(code)
            ws_url = _http_to_ws(server_url.rstrip("/")) + "/ws/edge"
            return _ConnectionConfig(mode="direct", base_url=ws_url)

        if code.startswith(_TOKEN_PREFIX):
            profile = _bootstrap_profile(code, "edge", device_name=self._edge_name)
            self._relay_url = profile["relay_url"]
            self._relay_access_token = profile["access_token"]
            return _ConnectionConfig(
                mode="relay",
                base_url=profile["relay_url"],
                access_token=profile["access_token"],
            )

        if code.startswith(("http://", "https://")):
            ws_url = _http_to_ws(code.rstrip("/")) + "/ws/edge"
            return _ConnectionConfig(mode="direct", base_url=ws_url)

        return _ConnectionConfig(
            mode="direct",
            base_url="ws://127.0.0.1:8000/ws/edge",
        )

    def _thread_entry(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connect_loop())
        finally:
            loop.close()

    async def _connect_loop(self) -> None:
        reconnect_delay = 3

        while not self._stop_event.is_set():
            try:
                # Resolve the connection on EACH attempt so a transient bootstrap
                # failure (e.g. the relay briefly unreachable at startup) is
                # retried rather than permanently killing the client thread.
                connection = self._resolve_connection()
                ws_url = connection.relay_edge_ws_url() if connection.mode == "relay" else connection.base_url

                register_payload = {
                    "type": "register",
                    "edge_name": self._edge_name,
                    "tools": [_wire_tool_schema(t) for t in list(self._tools.values())],
                    "tool_confirmation_policy": self._load_confirmation_policy(),
                }
                if connection.access_token:
                    register_payload["access_token"] = connection.access_token
                if self._register_connection_code:
                    register_payload["connection_code"] = self._register_connection_code

                async with websockets.connect(ws_url) as ws:
                    reconnect_delay = 3
                    await ws.send(json.dumps(register_payload))
                    self._connected = True
                    _LOG.info(
                        "Connected as [%s] with %d tool(s).",
                        self._edge_name,
                        len(self._tools),
                    )

                    self._in_flight.clear()

                    try:
                        while not self._stop_event.is_set():
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            except asyncio.TimeoutError:
                                continue

                            msg = json.loads(raw)
                            msg_type = msg.get("type")

                            if msg_type == "persist_tool_confirmation_policy":
                                aa = msg.get("always_allow") or []
                                fc = msg.get("force_confirm") or []
                                if isinstance(aa, list) and isinstance(fc, list):
                                    self._save_confirmation_policy(
                                        {
                                            "always_allow": [str(x) for x in aa if x],
                                            "force_confirm": [str(x) for x in fc if x],
                                        }
                                    )
                            elif msg_type == "tool_call":
                                asyncio.ensure_future(self._handle_tool_call(ws, msg))
                            elif msg_type == "cancel":
                                call_id = msg.get("call_id", "")
                                task = self._in_flight.get(call_id)
                                if task and not task.done():
                                    task.cancel()
                            elif msg_type == "register_rejected":
                                # The server refused this edge_name (already in
                                # use). Do NOT reconnect — that would just be
                                # rejected again. Stop and surface a clear error
                                # so the user picks a unique edge_name.
                                reason = msg.get("reason") or "edge_name already in use"
                                _LOG.error("Edge registration rejected by server: %s", reason)
                                self._emit_error(RuntimeError(f"Edge registration rejected: {reason}"))
                                self._stop_event.set()
                                return
                            elif msg_type == "register_warning":
                                # Some tools were not mounted (e.g. provider-invalid
                                # names). Surface them so they aren't lost silently.
                                dropped = msg.get("skipped_tools") or []
                                _LOG.warning(
                                    "Server did not mount %d tool(s): %s — %s",
                                    len(dropped),
                                    ", ".join(str(t) for t in dropped),
                                    msg.get("message") or "",
                                )
                    finally:
                        self._connected = False

            except asyncio.CancelledError:
                self._cancel_in_flight()
                self._connected = False
                break
            except Exception as exc:
                self._cancel_in_flight()
                self._connected = False
                if self._stop_event.is_set():
                    break
                self._emit_error(exc)
                wait = _reconnect_delay_sec_with_jitter(reconnect_delay)
                _LOG.warning("Connection lost: %s. Reconnecting in %.1fs...", exc, wait)
                await asyncio.sleep(wait)
                reconnect_delay = min(reconnect_delay * 2, 30)

    async def _handle_tool_call(self, ws, msg: dict) -> None:
        tool_name = msg.get("name", "")
        arguments = msg.get("arguments", {})
        call_id = msg.get("call_id", "unknown")

        cancelled = False
        tool = self._tools.get(tool_name)
        if tool is None:
            result = f"Error: Tool '{tool_name}' is not registered on this edge."
        else:
            func = tool["callable"]

            async def _execute():
                if inspect.iscoroutinefunction(func):
                    return await func(**arguments)
                else:
                    return await asyncio.get_running_loop().run_in_executor(None, lambda: func(**arguments))

            exec_task = asyncio.ensure_future(_execute())
            self._in_flight[call_id] = exec_task

            try:
                result = await exec_task
            except asyncio.CancelledError:
                cancelled = True
                result = f"Cancelled: Tool '{tool_name}' execution was cancelled by server."
            except Exception as exc:
                result = f"Error executing tool '{tool_name}': {exc}"

        self._in_flight.pop(call_id, None)

        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "tool_result",
                        "call_id": call_id,
                        "result": str(result),
                        "cancelled": cancelled,
                    }
                )
            )
        except Exception:
            pass
