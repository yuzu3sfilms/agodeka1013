"""Small duplicate-event guard for LINE webhook redelivery.

LINE may deliver the same webhookEventId more than once.  We only mark an
ID after the event has been handled, so a failed first attempt remains
eligible for redelivery.
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_HANDLED: dict[str, float] = {}
_TTL_SECONDS = 24 * 60 * 60


def _prune(now: float) -> None:
    expired = [event_id for event_id, ts in _HANDLED.items() if now - ts > _TTL_SECONDS]
    for event_id in expired:
        _HANDLED.pop(event_id, None)


def was_handled(event_id: str) -> bool:
    if not event_id:
        return False
    now = time.time()
    with _LOCK:
        _prune(now)
        return event_id in _HANDLED


def mark_handled(event_id: str) -> None:
    if not event_id:
        return
    now = time.time()
    with _LOCK:
        _prune(now)
        _HANDLED[event_id] = now
