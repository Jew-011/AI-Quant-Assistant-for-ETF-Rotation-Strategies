"""
Pattern 16: Resource-aware Optimization.

Tracks per-invocation resources:
- Tokens in/out per LLM call (via a LangChain callback handler)
- Tool call count & per-tool latency
- Wall-clock per node
- Cost estimation (configurable per model)

The results are aggregated per ``thread_id`` and exposed via ``ResourceTracker``
so that the Finaliser can include a "cost of this response" footer, and the
frontend can render a dashboard.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

try:  # pragma: no cover - callback base is a very stable API
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:  # pragma: no cover
    BaseCallbackHandler = object  # type: ignore


# Cheap, conservative defaults (per 1K tokens, USD). The base table below is
# always present; if ``config/models.yaml`` exists, its entries are merged on
# top so the model picker in the frontend stays the single source of truth.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "deepseek-v3.2":      {"in": 0.00027, "out": 0.00110},
    "deepseek-chat":      {"in": 0.00027, "out": 0.00110},
    "gpt-4o-mini":        {"in": 0.00015, "out": 0.00060},
    "gpt-4o":             {"in": 0.00250, "out": 0.01000},
    "default":            {"in": 0.00050, "out": 0.00200},
}


def _merge_model_costs_from_yaml() -> None:
    """Pull pricing for every model declared in ``config/models.yaml``."""
    import os
    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config",
        "models.yaml",
    )
    try:
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (FileNotFoundError, ImportError, OSError):
        return
    except Exception:
        return
    for it in raw.get("models") or []:
        try:
            mid = str(it["id"])
            MODEL_COSTS[mid] = {
                "in":  float(it.get("price_in", MODEL_COSTS["default"]["in"])),
                "out": float(it.get("price_out", MODEL_COSTS["default"]["out"])),
            }
        except (KeyError, TypeError, ValueError):
            continue


_merge_model_costs_from_yaml()


@dataclass
class ResourceRecord:
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    tool_calls: int = 0
    tool_latency_ms: float = 0.0
    node_latency_ms: dict[str, float] = field(default_factory=dict)
    tools_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "tool_calls": self.tool_calls,
            "tool_latency_ms": round(self.tool_latency_ms, 2),
            "node_latency_ms": {k: round(v, 2) for k, v in self.node_latency_ms.items()},
            "tools_breakdown": dict(self.tools_breakdown),
        }


class ResourceTracker:
    """Thread-safe per-thread resource accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, ResourceRecord] = defaultdict(ResourceRecord)

    def get(self, thread_id: str) -> ResourceRecord:
        with self._lock:
            return self._records[thread_id]

    def reset(self, thread_id: str) -> None:
        with self._lock:
            self._records[thread_id] = ResourceRecord()

    def add_llm_usage(
        self,
        thread_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        cost_cfg = MODEL_COSTS.get(model, MODEL_COSTS["default"])
        cost = (
            prompt_tokens / 1000 * cost_cfg["in"]
            + completion_tokens / 1000 * cost_cfg["out"]
        )
        with self._lock:
            rec = self._records[thread_id]
            rec.llm_calls += 1
            rec.prompt_tokens += prompt_tokens
            rec.completion_tokens += completion_tokens
            rec.total_tokens += prompt_tokens + completion_tokens
            rec.estimated_cost_usd += cost

    def add_tool_call(self, thread_id: str, tool_name: str, latency_ms: float) -> None:
        with self._lock:
            rec = self._records[thread_id]
            rec.tool_calls += 1
            rec.tool_latency_ms += latency_ms
            rec.tools_breakdown[tool_name] = rec.tools_breakdown.get(tool_name, 0) + 1

    def add_node_time(self, thread_id: str, node: str, latency_ms: float) -> None:
        with self._lock:
            rec = self._records[thread_id]
            rec.node_latency_ms[node] = rec.node_latency_ms.get(node, 0.0) + latency_ms

    def summary(self, thread_id: str) -> dict:
        return self.get(thread_id).to_dict()

    def all_threads(self) -> list[str]:
        with self._lock:
            return list(self._records.keys())


RESOURCE_TRACKER = ResourceTracker()


class CostCallbackHandler(BaseCallbackHandler):  # type: ignore[misc]
    """LangChain callback handler that feeds token usage into RESOURCE_TRACKER."""

    def __init__(self, thread_id: str, default_model: str = "default") -> None:
        super().__init__()
        self.thread_id = thread_id
        self.default_model = default_model

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: D401
        try:
            usage = {}
            if hasattr(response, "llm_output") and isinstance(response.llm_output, dict):
                usage = response.llm_output.get("token_usage") or {}
            if not usage and hasattr(response, "generations"):
                for gens in response.generations:
                    for g in gens:
                        meta = getattr(g, "generation_info", None) or {}
                        usage = meta.get("token_usage") or usage
                        if hasattr(g, "message"):
                            um = getattr(g.message, "usage_metadata", None)
                            if um:
                                usage = {
                                    "prompt_tokens": um.get("input_tokens", 0),
                                    "completion_tokens": um.get("output_tokens", 0),
                                }
            prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion = int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
            RESOURCE_TRACKER.add_llm_usage(
                self.thread_id, self.default_model, prompt, completion
            )
        except Exception:
            pass


class NodeTimer:
    """Context manager to time a graph node and auto-record into the tracker."""

    def __init__(self, thread_id: str, node_name: str) -> None:
        self.thread_id = thread_id
        self.node_name = node_name
        self._t0 = 0.0

    def __enter__(self) -> "NodeTimer":
        self._t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = (time.time() - self._t0) * 1000.0
        RESOURCE_TRACKER.add_node_time(self.thread_id, self.node_name, elapsed_ms)


def resource_snippet(thread_id: str) -> str:
    """Markdown summary for injection into the finaliser or UI."""
    rec = RESOURCE_TRACKER.get(thread_id)
    if rec.total_tokens == 0 and rec.tool_calls == 0:
        return ""
    top_tools = sorted(rec.tools_breakdown.items(), key=lambda x: -x[1])[:5]
    top_tools_str = ", ".join(f"{t}×{c}" for t, c in top_tools) if top_tools else "none"
    return (
        "## Resources (Pattern 16)\n"
        f"- LLM calls: {rec.llm_calls}, tokens in/out: "
        f"{rec.prompt_tokens}/{rec.completion_tokens} (total {rec.total_tokens})\n"
        f"- Estimated cost: ${rec.estimated_cost_usd:.5f}\n"
        f"- Tool calls: {rec.tool_calls} (top: {top_tools_str})\n"
        f"- Total tool latency: {rec.tool_latency_ms:.0f} ms"
    )
