from enum import Enum

from pydantic import BaseModel, Field


class TaskKey(str, Enum):
    GENERIC = "generic"
    RESEARCH_WEEKLY_REPORT = "research_weekly_report"
    RESEARCH_OVERLAY_ADJUSTMENT = "research_overlay_adjustment"
    RESEARCH_BACKTEST_COMPARE = "research_backtest_compare"
    RESEARCH_CONFLICT_CHECK = "research_conflict_check"
    RM_CLIENT_PORTFOLIO = "rm_client_portfolio"
    RM_EXPLAIN_PERFORMANCE = "rm_explain_performance"
    RM_BATCH_TALKING_POINTS = "rm_batch_talking_points"
    RM_MARKET_SPECIFIC = "rm_market_specific"
    COMPLIANCE_TRACE_REVIEW = "compliance_trace_review"
    COMPLIANCE_RISK_CHECK = "compliance_risk_check"
    COMPLIANCE_VETO_AUDIT = "compliance_veto_audit"
    COMPLIANCE_DRAWDOWN_CHECK = "compliance_drawdown_check"


class DataStrategy(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    HISTORY_FIRST = "history_first"
    FRESH_SCAN = "fresh_scan"
    HYBRID = "hybrid"


class RouterDecision(BaseModel):
    task_key: TaskKey = Field(
        description="The task type that best matches the current user request."
    )
    data_strategy: DataStrategy = Field(
        description=(
            "Recommended data strategy: direct answer, history-first, "
            "fresh-scan, or hybrid (history + current data)."
        )
    )
    should_use_tools: bool = Field(
        description="Whether the task should enter the tool-execution stage."
    )
    requires_trace_save: bool = Field(
        description="Whether a Decision Trace should be saved after this task."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence of this routing decision."
    )
    route_reason: str = Field(
        description="One sentence explaining why this classification was chosen."
    )
