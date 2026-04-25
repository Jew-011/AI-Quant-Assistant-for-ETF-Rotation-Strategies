"""
Pattern usage log - a thread-local accumulator that records which design patterns
were invoked during a single run. Enables the frontend to display a "Patterns Used"
badge for every agent response.

This is a lightweight in-memory log keyed by thread_id (matches LangGraph thread).
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from typing import Any


class PatternLog:
    """Thread-safe accumulator of pattern invocation events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def log(
        self,
        thread_id: str,
        pattern_id: int,
        pattern_name: str,
        node: str,
        detail: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "pattern_id": pattern_id,
            "pattern_name": pattern_name,
            "node": node,
            "detail": detail,
            "extra": extra or {},
        }
        with self._lock:
            self._events[thread_id].append(event)

    def get(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(thread_id, []))

    def clear(self, thread_id: str) -> None:
        with self._lock:
            self._events.pop(thread_id, None)

    def summary(self, thread_id: str) -> dict[int, int]:
        """Return {pattern_id: count} for the given thread."""
        with self._lock:
            events = self._events.get(thread_id, [])
        counter: dict[int, int] = defaultdict(int)
        for e in events:
            counter[e["pattern_id"]] += 1
        return dict(counter)


PATTERN_LOG = PatternLog()


def log_pattern_use(
    thread_id: str,
    pattern_id: int,
    pattern_name: str,
    node: str,
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Helper to record that a pattern was invoked. Thread-safe."""
    PATTERN_LOG.log(thread_id, pattern_id, pattern_name, node, detail, extra)
