"""
Progress reporting channel — bridges long-running backend work to whatever
frontend is watching (Streamlit `st.status`, CLI tqdm, plain print, …).

Design goals
------------
1. Backend code stays UI-agnostic: it calls ``emit(phase, label)`` and never
   touches Streamlit.
2. Multiple emitters can coexist (e.g. logging to stdout AND streaming to a
   Streamlit status box) by chaining callbacks.
3. Thread-safe ring buffer so parallel workers (multi-agent debate, parallel
   backtests) can append concurrently without locking the main thread.

Usage from a backend function:

    def run_long_task(progress_cb=None):
        emit = ProgressEmitter(progress_cb)
        emit("step1", "Pulling industry data")
        ...
        emit("done", "Task complete", level="success")

Usage from the frontend (Streamlit):

    with progress_view() as cb:
        run_long_task(progress_cb=cb)

If no callback is provided the emitter falls back to a no-op so existing CLI
callers keep working without modification.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Optional

ProgressLevel = Literal["info", "success", "warn", "error"]
ProgressCallback = Callable[[str, str, ProgressLevel], None]


@dataclass
class ProgressEvent:
    """A single timeline entry."""

    phase: str                # short machine ID, e.g. "weekly_prepare"
    label: str                # human-readable, already localised
    level: ProgressLevel = "info"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "label": self.label,
            "level": self.level,
            "ts": self.ts,
        }


class ProgressEmitter:
    """Thread-safe progress emitter with an optional sink callback."""

    def __init__(
        self,
        sink: Optional[ProgressCallback] = None,
        *,
        buffer_size: int = 500,
    ):
        self._sink = sink
        self._buffer: deque[ProgressEvent] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    @property
    def has_sink(self) -> bool:
        return self._sink is not None

    def emit(
        self,
        phase: str,
        label: str,
        *,
        level: ProgressLevel = "info",
    ) -> None:
        evt = ProgressEvent(phase=phase, label=label, level=level)
        with self._lock:
            self._buffer.append(evt)
        if self._sink is not None:
            try:
                self._sink(phase, label, level)
            except Exception:
                # Never let a misbehaving frontend break the backend.
                pass

    def history(self) -> list[ProgressEvent]:
        with self._lock:
            return list(self._buffer)

    def __call__(
        self,
        phase: str,
        label: str,
        *,
        level: ProgressLevel = "info",
    ) -> None:
        """Allow the emitter itself to be passed as a `progress_cb`."""
        self.emit(phase, label, level=level)


# A sentinel emitter that swallows everything — handy as a default arg.
NULL_EMITTER = ProgressEmitter(sink=None)


# ---------------------------------------------------------------------------
# Human labels for LangGraph node names. The frontend passes the active UI
# language and looks up the appropriate string. Anything not in the map gets
# a generic "Working: <node>" label.
# ---------------------------------------------------------------------------
_NODE_LABELS: dict[str, dict[str, str]] = {
    # Generic / fallback
    "start":            {"en": "Starting…",                 "zh": "启动中…"},
    "done":             {"en": "Done",                       "zh": "完成"},
    "failed":           {"en": "Failed",                     "zh": "失败"},
    "input_guardrail":  {"en": "Input guardrail check",      "zh": "输入护栏检查"},
    "output_guardrail": {"en": "Output guardrail check",     "zh": "输出护栏检查"},
    "memory_recall":    {"en": "Recalling long-term memory", "zh": "调取长期记忆"},
    "router":           {"en": "Routing the task",           "zh": "路由任务"},
    "planner":          {"en": "Planning the workflow",      "zh": "规划工作流"},
    "executor":         {"en": "Calling tools",              "zh": "调用工具"},
    "tools":            {"en": "Tool execution",             "zh": "工具执行"},
    "goal_update":      {"en": "Updating goal progress",     "zh": "更新目标进度"},
    "finalize":         {"en": "Composing final answer",     "zh": "撰写最终答复"},
    "reflect":          {"en": "Reflecting on the answer",   "zh": "反思与修订"},

    # Subgraph nodes
    "weekly_prepare":      {"en": "Pulling data & computing factors",
                            "zh": "拉取数据并计算因子"},
    "weekly_persist":      {"en": "Rendering report & saving Decision Trace",
                            "zh": "渲染报告并保存决策轨迹"},
    "trace_history":       {"en": "Loading Decision-Trace history",
                            "zh": "加载历史决策轨迹"},
    "trace_review":        {"en": "Reviewing past traces",   "zh": "审阅历史轨迹"},
    "backtest_compare":    {"en": "Running backtest comparison",
                            "zh": "执行回测对比"},
    "conflict_check":      {"en": "Checking signal conflicts",
                            "zh": "检查信号冲突"},
    "rm_explain":          {"en": "Building client-facing explanation",
                            "zh": "撰写客户解释"},
    "rm_portfolio_prepare":{"en": "Preparing RM portfolio",  "zh": "准备 RM 组合"},
    "rm_portfolio_persist":{"en": "Saving RM portfolio",      "zh": "保存 RM 组合"},
    "compliance_risk":     {"en": "Running compliance risk scan",
                            "zh": "执行合规风险扫描"},
    "multi_agent_debate":  {"en": "Multi-agent debate (Quant · Macro · Risk)",
                            "zh": "多智能体辩论（量化·宏观·风控）"},

    # Multi-agent inner phases (emitted from run_debate_parallel)
    "debate.evidence":  {"en": "Gathering evidence (factors, news, overlay)",
                         "zh": "收集证据（因子、新闻、Overlay）"},
    "debate.specialists": {"en": "Running 3 specialists in parallel",
                           "zh": "并行运行 3 位专家"},
    "debate.specialist_done": {"en": "{role} agent finished",
                               "zh": "{role} 智能体完成"},
    "debate.coordinator": {"en": "Coordinator aggregating verdict",
                           "zh": "协调者汇总裁决"},
    "debate.translate":   {"en": "Translating result to the other language",
                           "zh": "生成另一种语言的镜像副本"},
    "debate.complete":    {"en": "Debate complete", "zh": "辩论完成"},

    # Backtest inner phases
    "backtest.start":   {"en": "Starting backtest ({freq})",
                         "zh": "开始回测（{freq}）"},
    "backtest.done":    {"en": "Backtest complete ({freq})",
                         "zh": "回测完成（{freq}）"},
}


def label_for_node(node: str, lang: str = "en", **fmt) -> str:
    """Look up a localised label for a node / phase id.

    Unknown nodes get a generic "Working: <node>" / "处理中: <node>" label
    so progress UX still works for ad-hoc events that haven't been added
    to ``_NODE_LABELS`` yet.
    """
    entry = _NODE_LABELS.get(node)
    if not entry:
        return f"Working: {node}" if lang == "en" else f"处理中：{node}"
    raw = entry.get(lang) or entry.get("en") or node
    if fmt:
        try:
            return raw.format(**fmt)
        except (KeyError, IndexError):
            return raw
    return raw


def chain_callbacks(*callbacks: Optional[ProgressCallback]) -> Optional[ProgressCallback]:
    """Compose multiple sinks into one (skipping None entries)."""
    real = [cb for cb in callbacks if cb is not None]
    if not real:
        return None
    if len(real) == 1:
        return real[0]

    def _fanout(phase: str, label: str, level: ProgressLevel) -> None:
        for cb in real:
            try:
                cb(phase, label, level)
            except Exception:
                pass

    return _fanout


__all__ = [
    "ProgressCallback",
    "ProgressEvent",
    "ProgressEmitter",
    "ProgressLevel",
    "NULL_EMITTER",
    "label_for_node",
    "chain_callbacks",
]
