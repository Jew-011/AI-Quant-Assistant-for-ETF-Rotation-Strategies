from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # --- Core message + routing state (legacy) ---
    messages: Annotated[list, add_messages]
    user_input: str
    market: str
    role: str  # researcher | rm | compliance
    client_risk_level: Optional[str]  # R1-R5, only for RM role
    task_key: str
    route_reason: str
    route_confidence: float
    data_strategy: str
    should_use_tools: bool
    requires_trace_save: bool
    execution_plan: str
    tool_call_count: int
    last_tool_signature: str
    repeated_tool_call_count: int
    stop_reason: str
    workflow_context: str
    task_payload: dict
    latest_trace_path: str

    # --- New A+ pattern fields ---
    thread_id: str                       # for pattern log, memory, resource tracker
    output_language: str                 # "en" | "zh" — follows UI language from the frontend

    # Pattern 11: Goal Setting & Monitoring
    goal_state: dict                     # serialised GoalState
    goal_progress: float                 # 0..1 checklist completion

    # Pattern 18: Guardrails
    input_guardrail: dict                # GuardrailResult.to_dict()
    output_guardrail: dict
    hitl_request: dict                   # optional HITL record (if generated)
    blocked: bool                        # short-circuit flag

    # Pattern 8: Long-term Memory
    memory_snippet: str                  # text block appended to prompts

    # Pattern 4: Reflection
    reflection_rounds: list              # [{round, critique, revised}]
    reflected: bool

    # Pattern 7/15/17: Multi-agent debate
    debate_result: dict                  # run_debate_parallel output

    # Pattern 10: MCP
    mcp_enabled: bool

    # Pattern 16: Resource-aware
    resource_usage: dict                 # ResourceRecord.to_dict()

    # Generic extension bag
    extra: dict[str, Any]
