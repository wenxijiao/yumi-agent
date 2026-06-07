"""Background thread that subscribes to ``/timer-events`` NDJSON stream."""

from __future__ import annotations

import json
import queue
import threading
import time

import requests
from kumi.logging_config import get_logger

logger = get_logger(__name__)

timer_event_queue: queue.Queue = queue.Queue()
_timer_listener_started = False
_timer_listener_lock = threading.Lock()


def start_timer_listener(base_url: str, headers: dict) -> None:
    """Start a daemon thread that forwards timer NDJSON events into ``timer_event_queue``."""
    global _timer_listener_started
    with _timer_listener_lock:
        if _timer_listener_started:
            return
        _timer_listener_started = True

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
                            if data.get("type") == "heartbeat":
                                continue
                            timer_event_queue.put(data)
                        except json.JSONDecodeError:
                            pass
            except Exception as loop_exc:
                logger.debug("Timer listener loop: %s", loop_exc)
                time.sleep(5)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
