"""Kumi Edge SDK — self-contained Python agent client.

Only external dependency: ``websockets`` (``pip install websockets``).
All auth, connection, and tool-schema logic is inlined so this file
can be dropped into any project without the full ``kumi`` package.
"""

import asyncio
import base64
import copy
import inspect
import json
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

_LOG_PREFIX = "[Kumi]"

_TOOL_CONFIRMATION_FILENAME = ".kumi_tool_confirmation.json"


def _reconnect_delay_sec_with_jitter(delay_sec: int) -> float:
    """Seconds to wait before reconnect, with ±500ms jitter (thundering herd mitigation)."""
    base_ms = delay_sec * 1000
    jitter = random.randint(-500, 500)
    return max(1.0, (base_ms + jitter) / 1000.0)


# ── auth constants ──

_TOKEN_PREFIX = "kumi_"
_LAN_TOKEN_PREFIX = "kumi-lan_"
_LEGACY_LAN_PREFIXES = ("ml1_", "kumi_lan_")

# ── base64url helpers ──


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ── LAN code / credential decode ──


def _decode_lan_code(token: str) -> tuple[str, int]:
    """Decode a ``kumi-lan_`` token → ``(host, port)``."""
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
            raise ValueError("Invalid Kumi LAN code prefix.")

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
    """Decode a ``kumi_`` credential token → dict with at least ``relay_url``."""
    if not token.startswith(_TOKEN_PREFIX):
        raise ValueError("Invalid Kumi credential prefix.")
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
#  KumiAgent — public class
# ══════════════════════════════════════════════════════════════


class KumiAgent:
    """Embeddable Kumi edge client.

    Args:
        connection_code: Server connection code (LAN code, relay token,
            or WebSocket URL).  Falls back to ``KUMI_CONNECTION_CODE``
            / ``BRAIN_URL`` env vars, then ``kumi_tools/.env``.
        edge_name: Human-readable name shown in the server UI.
            Falls back to ``EDGE_NAME`` env var, then the hostname.
        env_path: Explicit path to a ``.env`` file.

    Usage::

        from kumi_sdk import KumiAgent

        agent = KumiAgent(
            connection_code="kumi-lan_...",
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
    ):
        if env_path:
            env_file = env_path
        else:
            kumi_tools_env = os.path.join(os.getcwd(), "kumi_tools", ".env")
            root_env = os.path.join(os.getcwd(), ".env")
            env_file = kumi_tools_env if os.path.isfile(kumi_tools_env) else root_env

        _load_env_file(env_file)

        self._policy_base_dir = os.path.dirname(os.path.abspath(env_file))

        self._connection_code = connection_code or os.getenv("KUMI_CONNECTION_CODE") or os.getenv("BRAIN_URL")
        self._edge_name = edge_name or os.getenv("EDGE_NAME") or socket.gethostname()

        self._tools: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[str, asyncio.Task] = {}

    def _confirmation_policy_path(self) -> str:
        override = (os.getenv("KUMI_TOOL_CONFIRMATION_PATH") or "").strip()
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
        always_include: bool = False,
        allow_proactive: bool = False,
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
        in the web UI or in ``kumi --chat`` (not on the edge device).

        **Tool routing:** Set ``always_include=True`` for edge tools whose
        schema must be exposed to the model on every turn, bypassing dynamic
        edge-tool retrieval for that tool.

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
                Kumi UI or terminal chat before the server invokes this tool
                on the edge.
            always_include: If True, this edge tool is included in every
                model request. Defaults to False.
            allow_proactive: If True, this read-only tool may be used by
                proactive messaging. Defaults to False.
            proactive_context: If True, proactive messaging calls this tool
                before generation and injects the result as context.
            proactive_context_args: Fixed arguments for proactive context calls.
            proactive_context_description: Label used when injecting the result.
        """
        schema = _build_tool_schema(func, name, description, params, returns)
        if timeout is not None:
            schema["timeout"] = timeout
        tool_name = schema["function"]["name"]
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

    def run_in_background(self) -> None:
        """Start the edge client in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        if not self._tools:
            print(f"{_LOG_PREFIX} Warning: no tools registered.")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._thread_entry,
            name="kumi-agent",
            daemon=True,
        )
        self._thread.start()

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
        relay_url = os.getenv("KUMI_RELAY_URL")
        access_token = os.getenv("KUMI_ACCESS_TOKEN")
        if relay_url and access_token:
            return _ConnectionConfig(
                mode="relay",
                base_url=relay_url.rstrip("/"),
                access_token=access_token,
            )

        code = self._connection_code or ""

        if code.startswith(("ws://", "wss://")):
            return _ConnectionConfig(mode="direct", base_url=code)

        if code.startswith(_LAN_TOKEN_PREFIX) or any(code.startswith(p) for p in _LEGACY_LAN_PREFIXES):
            server_url = _parse_lan_code(code)
            ws_url = _http_to_ws(server_url.rstrip("/")) + "/ws/edge"
            return _ConnectionConfig(mode="direct", base_url=ws_url)

        if code.startswith(_TOKEN_PREFIX):
            profile = _bootstrap_profile(code, "edge", device_name=self._edge_name)
            os.environ["KUMI_RELAY_URL"] = profile["relay_url"]
            os.environ["KUMI_ACCESS_TOKEN"] = profile["access_token"]
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
        try:
            connection = self._resolve_connection()
        except Exception as exc:
            print(f"{_LOG_PREFIX} Failed to resolve connection: {exc}")
            return

        if connection.mode == "relay":
            ws_url = connection.relay_edge_ws_url()
        else:
            ws_url = connection.base_url

        register_payload = {
            "type": "register",
            "edge_name": self._edge_name,
            "tools": [_wire_tool_schema(t) for t in list(self._tools.values())],
            "tool_confirmation_policy": self._load_confirmation_policy(),
        }
        if connection.access_token:
            register_payload["access_token"] = connection.access_token

        reconnect_delay = 3

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(ws_url) as ws:
                    reconnect_delay = 3
                    register_payload["tools"] = [_wire_tool_schema(t) for t in list(self._tools.values())]
                    register_payload["tool_confirmation_policy"] = self._load_confirmation_policy()
                    await ws.send(json.dumps(register_payload))
                    print(f"{_LOG_PREFIX} Connected as [{self._edge_name}] with {len(self._tools)} tool(s).")

                    self._in_flight.clear()

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

            except asyncio.CancelledError:
                self._cancel_in_flight()
                break
            except Exception as exc:
                self._cancel_in_flight()
                if self._stop_event.is_set():
                    break
                wait = _reconnect_delay_sec_with_jitter(reconnect_delay)
                print(f"{_LOG_PREFIX} Connection lost: {exc}. Reconnecting in {wait:.1f}s...")
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
