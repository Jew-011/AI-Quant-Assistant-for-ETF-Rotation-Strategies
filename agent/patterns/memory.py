"""
Pattern 8: Memory.

LangGraph's MemorySaver already provides short-term (within-thread) conversation
memory. This module adds **long-term, cross-session memory**:

- Client profiles:     client_risk_level, preferred markets, past queries.
- Conversation summary: compressed history, auto-summarized every N turns.
- Preference signals:  which tasks a user runs often (for UI personalisation).

Storage: JSON-per-thread under ``traces/memory/``. Simple, inspectable, demo-able.
For production we would back this with Redis/Postgres behind a common interface.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from agent.patterns.pattern_log import log_pattern_use

MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "traces", "memory"
)
os.makedirs(MEMORY_DIR, exist_ok=True)

MAX_QUERY_HISTORY = 50


@dataclass
class ClientProfile:
    client_id: str = "default"
    risk_level: str | None = None       # R1..R5
    preferred_market: str | None = None
    preferred_sectors: list[str] = field(default_factory=list)
    vetoed_sectors: list[str] = field(default_factory=list)
    note: str = ""
    updated_at: str = ""


@dataclass
class UserMemory:
    thread_id: str
    profile: ClientProfile
    query_history: list[dict[str, Any]] = field(default_factory=list)
    task_counter: dict[str, int] = field(default_factory=dict)
    rolling_summary: str = ""
    last_trace_path: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _path(thread_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in thread_id)
    return os.path.join(MEMORY_DIR, f"{safe}.json")


def load_memory(thread_id: str) -> UserMemory:
    """Load or initialise long-term memory for a thread."""
    path = _path(thread_id)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            profile = ClientProfile(**raw.get("profile", {"client_id": thread_id}))
            raw["profile"] = profile
            return UserMemory(**raw)
        except Exception:
            pass
    now = datetime.now().isoformat(timespec="seconds")
    return UserMemory(
        thread_id=thread_id,
        profile=ClientProfile(client_id=thread_id, updated_at=now),
        created_at=now,
        updated_at=now,
    )


def save_memory(mem: UserMemory) -> None:
    mem.updated_at = datetime.now().isoformat(timespec="seconds")
    mem.profile.updated_at = mem.updated_at
    path = _path(mem.thread_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mem.to_dict(), f, ensure_ascii=False, indent=2)


def record_query(
    thread_id: str,
    user_input: str,
    task_key: str,
    market: str,
    role: str,
    client_risk_level: str | None = None,
) -> UserMemory:
    """Persist a single query event and update task counters."""
    log_pattern_use(
        thread_id,
        8,
        "Memory",
        "record_query",
        f"task={task_key}",
    )
    mem = load_memory(thread_id)
    mem.query_history.append(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "user_input": user_input[:400],
            "task_key": task_key,
            "market": market,
            "role": role,
        }
    )
    if len(mem.query_history) > MAX_QUERY_HISTORY:
        mem.query_history = mem.query_history[-MAX_QUERY_HISTORY:]
    mem.task_counter[task_key] = mem.task_counter.get(task_key, 0) + 1
    if client_risk_level and role == "rm":
        mem.profile.risk_level = client_risk_level
    if market:
        mem.profile.preferred_market = market
    save_memory(mem)
    return mem


def update_profile(thread_id: str, **fields) -> ClientProfile:
    """Selectively update profile fields (e.g. from UI)."""
    mem = load_memory(thread_id)
    for k, v in fields.items():
        if hasattr(mem.profile, k) and v is not None:
            setattr(mem.profile, k, v)
    save_memory(mem)
    return mem.profile


def update_rolling_summary(thread_id: str, new_summary: str) -> None:
    mem = load_memory(thread_id)
    mem.rolling_summary = new_summary
    save_memory(mem)


def set_last_trace(thread_id: str, trace_path: str) -> None:
    mem = load_memory(thread_id)
    mem.last_trace_path = trace_path
    save_memory(mem)


def memory_context_snippet(thread_id: str) -> str:
    """Return a compact text block suitable for injecting into a system prompt."""
    mem = load_memory(thread_id)
    if not mem.query_history and not mem.profile.risk_level:
        return ""
    recent = mem.query_history[-3:]
    recent_str = "\n".join(
        f"  - [{r.get('ts', '')}] ({r.get('task_key', '?')}) {r.get('user_input', '')[:60]}"
        for r in recent
    )
    top_tasks = sorted(mem.task_counter.items(), key=lambda x: -x[1])[:3]
    top_tasks_str = ", ".join(f"{k}×{v}" for k, v in top_tasks) if top_tasks else "none"
    return (
        "## Long-term memory (Pattern 8)\n"
        f"- Client risk level: {mem.profile.risk_level or 'not set'}\n"
        f"- Preferred market: {mem.profile.preferred_market or 'not set'}\n"
        f"- Top used tasks: {top_tasks_str}\n"
        f"- Recent queries:\n{recent_str or '  - none'}\n"
        f"- Rolling summary: {mem.rolling_summary[:300] or 'none'}"
    )


def list_all_threads() -> list[str]:
    if not os.path.isdir(MEMORY_DIR):
        return []
    return [
        os.path.splitext(fn)[0]
        for fn in os.listdir(MEMORY_DIR)
        if fn.endswith(".json")
    ]
