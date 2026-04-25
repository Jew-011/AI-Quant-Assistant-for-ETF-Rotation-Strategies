"""
Pattern 11: Goal Setting and Monitoring.

Each user request is translated into an explicit ``GoalState`` object, and every
subsequent node checks off sub-goals as it completes them. This gives two
benefits:

1. **Explainability**: the UI renders a checklist of (sub_goal -> status).
2. **Early stop**: when all sub-goals are satisfied, the finaliser skips further
   tool calls.

The mapping from ``task_key`` to the expected goal template lives in
``TASK_GOAL_TEMPLATES``. Sub-goals are marked satisfied when their expected
signals (e.g. ``factor_df_computed``, ``etf_mapping_produced``) appear in the
task payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from agent.patterns.pattern_log import log_pattern_use


@dataclass
class SubGoal:
    id: str
    description: str
    signal_key: str          # the key in payload that satisfies this sub-goal
    satisfied: bool = False
    satisfied_at: str = ""

    def mark(self) -> None:
        self.satisfied = True
        self.satisfied_at = datetime.now().isoformat(timespec="seconds")


@dataclass
class GoalState:
    task_key: str
    objective: str
    sub_goals: list[SubGoal] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def progress(self) -> float:
        if not self.sub_goals:
            return 1.0
        return sum(1 for g in self.sub_goals if g.satisfied) / len(self.sub_goals)

    def is_complete(self) -> bool:
        return bool(self.sub_goals) and all(g.satisfied for g in self.sub_goals)

    def to_dict(self) -> dict:
        return asdict(self)


TASK_GOAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "research_weekly_report": {
        "objective": "Produce an approval-ready A-share sector-rotation weekly report",
        "sub_goals": [
            ("fetch_market_data", "Fetch market and ETF price data", "market_data_summary"),
            ("compute_factors", "Compute the 5 factors plus trend/consensus scores", "factor_summary"),
            ("map_quadrants", "Assign sectors to the four quadrants", "quadrant_distribution"),
            ("apply_overlay", "Apply observation pool and veto list", "observation_pool_filter"),
            ("map_etf", "Produce the ETF portfolio recommendation", "portfolio_recommendation"),
        ],
    },
    "rm_client_portfolio": {
        "objective": "Generate an ETF portfolio + talking points fit for the client risk level",
        "sub_goals": [
            ("compute_factors", "Compute factors for the period", "industries"),
            ("pick_sectors", "Filter candidate sectors", "industries"),
            ("map_etf", "Map sectors to ETFs", "mapped"),
        ],
    },
    "rm_explain_performance": {
        "objective": "Explain prior recommendation performance and produce client talking points",
        "sub_goals": [
            ("load_history", "Pull recent decision trace", "history"),
            ("enrich_news", "Add relevant news evidence", "news"),
        ],
    },
    "research_conflict_check": {
        "objective": "Check whether quantitative signals conflict with the observation pool / veto / news",
        "sub_goals": [
            ("compute_factors", "Compute factors", "market"),
            ("pick_golden", "Identify focus sectors in the Golden Zone", "golden_industries"),
            ("cross_validate_news", "Cross-validate with news", "news"),
        ],
    },
    "research_backtest_compare": {
        "objective": "Run a monthly vs weekly parameter backtest comparison",
        "sub_goals": [
            ("backtest_monthly", "Monthly rebalance backtest", "monthly"),
            ("backtest_weekly", "Weekly rebalance backtest", "weekly"),
        ],
    },
    "compliance_trace_review": {
        "objective": "Audit the completeness of the latest Decision Trace",
        "sub_goals": [
            ("locate_trace", "Locate the latest trace", "market"),
        ],
    },
    "compliance_risk_check": {
        "objective": "Run a compliance risk check on the current portfolio",
        "sub_goals": [
            ("load_trace", "Read the trace", "market"),
        ],
    },
    "generic": {
        "objective": "Answer the general question with a reasonable response",
        "sub_goals": [
            ("respond", "Produce the final answer", "final_response"),
        ],
    },
}


def init_goal_state(task_key: str, thread_id: str = "default") -> GoalState:
    """Build a GoalState from the task template."""
    log_pattern_use(
        thread_id,
        11,
        "Goal Setting & Monitoring",
        "init_goal",
        f"task={task_key}",
    )
    template = TASK_GOAL_TEMPLATES.get(task_key) or TASK_GOAL_TEMPLATES["generic"]
    sub_goals = [
        SubGoal(id=sid, description=desc, signal_key=sig)
        for (sid, desc, sig) in template["sub_goals"]
    ]
    return GoalState(
        task_key=task_key,
        objective=template["objective"],
        sub_goals=sub_goals,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )


def update_goal_progress(
    goal: GoalState, payload: dict, thread_id: str = "default"
) -> GoalState:
    """Mark sub-goals satisfied based on keys/values present in payload."""
    if not goal or not payload:
        return goal
    changed = 0
    for sg in goal.sub_goals:
        if sg.satisfied:
            continue
        val = payload.get(sg.signal_key)
        if val is None:
            continue
        if isinstance(val, (list, dict, str)) and not val:
            continue
        sg.mark()
        changed += 1
    if changed:
        log_pattern_use(
            thread_id,
            11,
            "Goal Setting & Monitoring",
            "progress_update",
            f"+{changed} sub-goals -> progress={goal.progress():.0%}",
        )
    if goal.is_complete() and not goal.completed_at:
        goal.completed_at = datetime.now().isoformat(timespec="seconds")
    return goal


def goal_progress_snippet(goal: GoalState) -> str:
    """Render the goal state as a markdown checklist for the finaliser prompt."""
    if not goal or not goal.sub_goals:
        return ""
    lines = [
        f"## Goal (Pattern 11)",
        f"- Objective: {goal.objective}",
        f"- Progress: {int(goal.progress() * 100)}% ({sum(1 for g in goal.sub_goals if g.satisfied)}/{len(goal.sub_goals)})",
        "- Sub-goals:",
    ]
    for sg in goal.sub_goals:
        mark = "✅" if sg.satisfied else "⬜"
        lines.append(f"  - {mark} {sg.id} — {sg.description}")
    return "\n".join(lines)
