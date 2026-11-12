"""Usage limits for the public "Ask the data" page (DL-026, guardrail 5).

- per visitor: at most PER_SESSION questions per browser session
- for everyone: at most PER_DAY questions per UTC day, shared by all visitors

The daily counter lives in the app's memory, so it resets if the app restarts.
The Anthropic account's monthly spend limit is the hard backstop.
"""
from __future__ import annotations

import datetime as dt
import threading

PER_SESSION = 10
PER_DAY = 300   # ~$0.10/day on Claude Haiku 5.5 at the tested median cost


class DailyCap:
    """Thread-safe count of questions per UTC day, shared across sessions."""

    def __init__(self, limit: int = PER_DAY, today=None):
        self.limit = limit
        self._today = today or (lambda: dt.datetime.now(dt.timezone.utc).date())
        self._lock = threading.Lock()
        self._day = None
        self._count = 0

    def try_take(self) -> bool:
        """Count one question if today's cap allows it."""
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    @property
    def used_today(self) -> int:
        with self._lock:
            return self._count if self._day == self._today() else 0


def session_allows(asked: int, limit: int = PER_SESSION) -> bool:
    return asked < limit
