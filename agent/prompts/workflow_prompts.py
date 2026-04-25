"""
Planner / Executor / Finalizer guidance prompts.

All strings are written in English. The locale-specific output-language
instruction is appended via ``with_lang`` so the answer the LLM produces
follows the UI language picked by the user.
"""
from __future__ import annotations

from agent.prompts._lang import with_lang


def build_planner_prompt(
    role: str,
    market: str,
    task_key: str,
    user_input: str,
    data_strategy: str = "fresh_scan",
    requires_trace_save: bool = False,
    client_risk_level: str | None = None,
    output_language: str = "en",
) -> str:
    risk_line = ""
    if role == "rm":
        risk_line = f"- Client risk level: {client_risk_level or 'not provided'}\n"

    prompt = f"""You are the Planner inside a controlled workflow. Your job is to break the user request into a clear, finite, executable plan.

Use the following context:
- Current role: {role}
- Current market: {market}
- Current task: {task_key}
- Data strategy: {data_strategy}
- Should save a trace at the end: {'yes' if requires_trace_save else 'no'}
{risk_line}- User request: {user_input}

Requirements:
1. Output a concise Markdown plan only. Do not call any tool. Do not produce the final answer.
2. The plan must contain four sections:
   - Goal
   - Suggested steps (3 to 6 steps)
   - Expected tools
   - Stop condition
3. Minimise tool calls — when historical traces can be reused, do not re-run a full scan.
4. If this is formal advice / formal weekly report / formal approval material, the plan must explicitly mention saving a trace at the end.
"""
    return with_lang(prompt, output_language)


def build_executor_guidance(
    plan: str,
    max_tool_calls: int,
    tool_call_count: int,
    data_strategy: str = "fresh_scan",
    requires_trace_save: bool = False,
    output_language: str = "en",
) -> str:
    remaining = max(max_tool_calls - tool_call_count, 0)
    prompt = f"""## Execution stage constraints
You are inside the controlled Executor stage. Stay strictly inside the given plan and do not expand the problem without a plan update.

### Current plan
{plan}

### Execution rules
1. Each round, take the single step closest to the current sub-goal.
2. If you already have enough information for a conclusion, output the final answer instead of calling more tools.
3. Do not call the same tool with the same arguments twice.
4. If a critical piece of data is missing, state the gap and its impact explicitly.
5. Current data strategy: `{data_strategy}`. If `history_first`, prefer reading historical traces first; if `fresh_scan`, prefer current analysis; if `hybrid`, combine history with current data per the plan.
6. {'This is formal advice / formal material — the run must end by saving a trace.' if requires_trace_save else 'This is not formal material — do not save a trace just for ceremony.'}

### Tool budget
- Max tool calls: {max_tool_calls}
- Used so far: {tool_call_count}
- Remaining budget: {remaining}
"""
    return with_lang(prompt, output_language)


def build_finalizer_guidance(
    stop_reason: str | None = None,
    output_language: str = "en",
) -> str:
    extra = ""
    if stop_reason:
        extra = (
            "\n### Stop reason\n"
            f"- {stop_reason}\n"
            "- Produce the most complete conclusion the available evidence supports, "
            "without over-extrapolating.\n"
        )

    prompt = f"""You are now in the Finalizer stage.
Do not call any tool. Produce the final answer from the existing context.

Requirements:
1. Clearly separate confirmed facts, reasoning, risk warnings, and open items.
2. If the run ended early due to a tool budget cap or repeated-call protection, be honest about the boundaries of your conclusion.
3. The output must match the current role and task scenario.
{extra}"""
    return with_lang(prompt, output_language)
