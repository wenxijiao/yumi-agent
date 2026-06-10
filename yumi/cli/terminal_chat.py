import base64
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import requests

from yumi.core.platform.security.connection import resolve_connection_config

DEFAULT_SESSION_ID = f"chat_{uuid.uuid4().hex[:12]}"


def _start_timer_listener(base_url: str, headers: dict, session_id: str):
    """Background thread that listens for timer events via SSE."""

    def _listen():
        url = f"{base_url}/timer-events"
        while True:
            try:
                with requests.get(url, headers=headers, stream=True, timeout=(10, None)) as resp:
                    if not resp.ok:
                        time.sleep(5)
                        continue
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "heartbeat":
                            continue
                        if data.get("session_id") != session_id:
                            continue
                        events = data.get("events", [])
                        text = "".join(e.get("content", "") for e in events if e.get("type") == "text").strip()
                        if text:
                            sys.stdout.write(f"\n⏰ Yumi: {text}\n\nYou: ")
                            sys.stdout.flush()
            except Exception:
                time.sleep(5)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


SLASH_HELP = """\
Available commands:
  /help                 Show this help message
  /prompt               Show current system prompt
  /prompt set <text>    Set a custom system prompt for this session
  /prompt default       Revert this session to the global default prompt
  /prompt global        Show the global default prompt
  /prompt global set <text>  Set the global default prompt
  /prompt global reset  Reset global prompt to built-in default
  /model                Show current model configuration
  /transcribe <path>    Transcribe an audio file and send it as a message
  /session              Show current session ID
  /clear                Clear chat history for this session
  /start_log            Append NDJSON chat traces under ~/.yumi/debug/chat_trace/ (server)
  /end_log              Stop chat tracing
"""


def _api_url(connection, path: str) -> str:
    return f"{connection.base_url}{path}"


def _handle_slash_command(user_input: str, session_id: str) -> bool:
    """Handle slash commands. Returns True if the input was a command."""
    stripped = user_input.strip()
    if not stripped.startswith("/"):
        return False

    connection = resolve_connection_config("chat")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"

    parts = stripped.split(None, 3)
    cmd = parts[0].lower()

    if cmd == "/help":
        print(SLASH_HELP)
        return True

    if cmd == "/session":
        print(f"  Session ID: {session_id}\n")
        return True

    if cmd == "/clear":
        try:
            r = requests.post(
                _api_url(connection, f"/clear?session_id={session_id}"),
                headers=headers,
                timeout=5,
            )
            if r.ok:
                print("  Chat history cleared.\n")
            else:
                print(f"  Failed: {r.text}\n")
        except Exception as exc:
            print(f"  Error: {exc}\n")
        return True

    if cmd == "/start_log":
        try:
            r = requests.put(
                _api_url(connection, "/config/chat-debug"),
                headers=headers,
                json={"session_id": session_id, "enabled": True},
                timeout=5,
            )
            if r.ok:
                p = r.json().get("trace_path") or ""
                print(f"  Chat debug ON. Trace: {p}\n")
            else:
                print(f"  Failed: {r.text}\n")
        except Exception as exc:
            print(f"  Error: {exc}\n")
        return True

    if cmd == "/end_log":
        try:
            r = requests.put(
                _api_url(connection, "/config/chat-debug"),
                headers=headers,
                json={"session_id": session_id, "enabled": False},
                timeout=5,
            )
            if r.ok:
                p = r.json().get("trace_path") or ""
                print(f"  Chat debug OFF. Last trace: {p}\n" if p else "  Chat debug OFF.\n")
            else:
                print(f"  Failed: {r.text}\n")
        except Exception as exc:
            print(f"  Error: {exc}\n")
        return True

    if cmd == "/model":
        try:
            r = requests.get(_api_url(connection, "/config/model"), headers=headers, timeout=5)
            if r.ok:
                cfg = r.json()
                print(f"  Chat:      {cfg.get('chat_provider', '?')} / {cfg.get('chat_model', '?')}")
                print(f"  Embedding: {cfg.get('embedding_provider', '?')} / {cfg.get('embedding_model', '?')}\n")
            else:
                print(f"  Failed: {r.text}\n")
        except Exception as exc:
            print(f"  Error: {exc}\n")
        return True

    if cmd == "/transcribe":
        path_text = stripped[len("/transcribe") :].strip()
        if not path_text:
            print("  Usage: /transcribe <audio-file-path>\n")
            return True
        p = Path(path_text).expanduser()
        if not p.is_file():
            print(f"  Audio file not found: {p}\n")
            return True
        try:
            raw = p.read_bytes()
            b64 = base64.standard_b64encode(raw).decode("ascii")
            r = requests.post(
                _api_url(connection, "/stt/transcribe"),
                json={"session_id": session_id, "filename": p.name, "content_base64": b64},
                headers=headers,
                timeout=600,
            )
            if not r.ok:
                print(f"  Transcription failed: {r.text}\n")
                return True
            text = str(r.json().get("text") or "").strip()
        except Exception as exc:
            print(f"  Transcription failed: {exc}\n")
            return True
        if not text:
            print("  Transcription returned empty text.\n")
            return True
        print(f"  Transcribed: {text}\n")
        chat_stream(text, session_id=session_id)
        return True

    if cmd == "/prompt":
        subcmd = parts[1].lower() if len(parts) > 1 else ""

        if subcmd == "global":
            sub2 = parts[2].lower() if len(parts) > 2 else ""
            if sub2 == "set":
                text = parts[3] if len(parts) > 3 else ""
                if not text:
                    print("  Usage: /prompt global set <text>\n")
                    return True
                try:
                    r = requests.put(
                        _api_url(connection, "/config/system-prompt"),
                        json={"system_prompt": text},
                        headers=headers,
                        timeout=5,
                    )
                    if r.ok:
                        print("  Global default prompt updated.\n")
                    else:
                        print(f"  Failed: {r.text}\n")
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                return True

            if sub2 == "reset":
                try:
                    r = requests.delete(
                        _api_url(connection, "/config/system-prompt"),
                        headers=headers,
                        timeout=5,
                    )
                    if r.ok:
                        print("  Global prompt reset to built-in default.\n")
                    else:
                        print(f"  Failed: {r.text}\n")
                except Exception as exc:
                    print(f"  Error: {exc}\n")
                return True

            try:
                r = requests.get(
                    _api_url(connection, "/config/system-prompt"),
                    headers=headers,
                    timeout=5,
                )
                if r.ok:
                    data = r.json()
                    label = "(default)" if data.get("is_default") else "(custom)"
                    print(f"  Global prompt {label}:")
                    print(f"  {data.get('system_prompt', '')}\n")
                else:
                    print(f"  Failed: {r.text}\n")
            except Exception as exc:
                print(f"  Error: {exc}\n")
            return True

        if subcmd == "set":
            text = " ".join(parts[2:]) if len(parts) > 2 else ""
            if not text:
                print("  Usage: /prompt set <text>\n")
                return True
            try:
                r = requests.put(
                    _api_url(connection, f"/config/session-prompt/{session_id}"),
                    json={"system_prompt": text},
                    headers=headers,
                    timeout=5,
                )
                if r.ok:
                    print("  Session prompt updated.\n")
                else:
                    print(f"  Failed: {r.text}\n")
            except Exception as exc:
                print(f"  Error: {exc}\n")
            return True

        if subcmd == "default":
            try:
                r = requests.delete(
                    _api_url(connection, f"/config/session-prompt/{session_id}"),
                    headers=headers,
                    timeout=5,
                )
                if r.ok:
                    print("  Session prompt reverted to global default.\n")
                else:
                    print(f"  Failed: {r.text}\n")
            except Exception as exc:
                print(f"  Error: {exc}\n")
            return True

        try:
            r = requests.get(
                _api_url(connection, f"/config/session-prompt/{session_id}"),
                headers=headers,
                timeout=5,
            )
            if r.ok:
                data = r.json()
                if data.get("is_custom"):
                    print("  Session prompt (custom):")
                    print(f"  {data.get('system_prompt', '')}\n")
                else:
                    print("  Session prompt: using global default")
                    print("  Use /prompt global to view, /prompt set <text> to customize.\n")
            else:
                print(f"  Failed: {r.text}\n")
        except Exception as exc:
            print(f"  Error: {exc}\n")
        return True

    print(f"  Unknown command: {cmd}")
    print("  Type /help for available commands.\n")
    return True


def chat_stream(prompt, session_id=DEFAULT_SESSION_ID):
    connection = resolve_connection_config("chat")
    url = f"{connection.base_url}/chat"
    payload = {"prompt": prompt, "session_id": session_id}
    headers = connection.auth_headers()
    target_name = "Yumi server"

    printed_text = False
    try:
        with requests.post(
            url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=(10, 300),
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                event = json.loads(line)
                event_type = event.get("type")

                if event_type == "text":
                    if not printed_text:
                        print("Yumi: ", end="", flush=True)
                        printed_text = True
                    print(event.get("content", ""), end="", flush=True)
                elif event_type == "tool_status":
                    if printed_text:
                        print()
                        printed_text = False
                    print(f"[Tool] {event.get('content', '')}")
                elif event_type == "tool_confirmation":
                    if printed_text:
                        print()
                        printed_text = False
                    call_id = event.get("call_id", "")
                    tname = event.get("tool_name", "")
                    args = event.get("arguments", {})
                    print("\n" + "=" * 50)
                    print("Tool call requires confirmation")
                    print(f"  Tool: {tname}")
                    print(f"  Arguments: {json.dumps(args, ensure_ascii=False)}")
                    print("\n  [1] Deny   [2] Allow   [3] Always allow")
                    decision = None
                    while decision is None:
                        raw = input("Choose (1/2/3): ").strip().lower()
                        if raw in ("1", "d", "deny", "n", "no"):
                            decision = "deny"
                        elif raw in ("2", "a", "y", "yes", "allow"):
                            decision = "allow"
                        elif raw in ("3", "always", "always_allow"):
                            decision = "always_allow"
                        else:
                            print("  Enter 1, 2, or 3")
                    try:
                        c_url = _api_url(connection, "/tools/confirm")
                        h = connection.auth_headers()
                        h["Content-Type"] = "application/json"
                        cr = requests.post(
                            c_url,
                            json={"call_id": call_id, "decision": decision},
                            headers=h,
                            timeout=120,
                        )
                        if not cr.ok:
                            print(f"  [Error] Confirmation request failed: {cr.text}")
                    except Exception as exc:
                        print(f"  [Error] Confirmation request failed: {exc}")
                elif event_type == "error":
                    if printed_text:
                        print()
                    print(f"[Error] {event.get('content', 'Unknown backend error.')}")

            print("\n")

    except requests.exceptions.ConnectionError:
        print(f"\n[Error] Cannot connect to the {target_name}.\n")
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"\n[Error] Something unexpected happened: {exc}\n")


def main() -> None:
    """Run the interactive terminal chat REPL."""
    print("Yumi terminal chat started. Type 'exit' or 'q' to quit.")
    print("Type /help for available commands.")
    print(f"Session: {DEFAULT_SESSION_ID}\n")

    connection = resolve_connection_config("chat")
    _start_timer_listener(connection.base_url, connection.auth_headers(), DEFAULT_SESSION_ID)

    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            break
        if user_input.strip() == "":
            continue

        if _handle_slash_command(user_input, DEFAULT_SESSION_ID):
            continue

        chat_stream(user_input, DEFAULT_SESSION_ID)


if __name__ == "__main__":
    main()
