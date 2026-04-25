from agent.prompts._lang import with_lang
from agent.prompts.task_prompts import TASK_SUMMARIES, get_allowed_task_keys_for_role


def build_router_prompt(
    role: str,
    market: str,
    user_input: str,
    client_risk_level: str | None = None,
    output_language: str = "en",
) -> str:
    allowed_task_keys = get_allowed_task_keys_for_role(role)
    task_lines = [f"- `{task_key}`: {TASK_SUMMARIES[task_key]}" for task_key in allowed_task_keys]
    risk_line = ""
    if role == "rm":
        risk_line = f"- Client risk level: {client_risk_level or 'not provided'}\n"

    prompt = f"""You are a structured-output Router. Your job is to map the user request to one specific task type and emit a structured decision the downstream workflow can consume.

## Current context
- Current role: {role}
- Current market: {market}
{risk_line}- User request: {user_input}

## You may pick exactly one of the following task types
{chr(10).join(task_lines)}

## Routing rules
1. Pick exactly one best-matching `task_key`.
2. `data_strategy` semantics:
   - `direct_answer` — no tool needed, or a direct explanation suffices.
   - `history_first` — read historical traces / prior conclusions first.
   - `fresh_scan` — run a current-market scan, factor calc, quadrant, mapping.
   - `hybrid` — combine historical and current data.
3. Set `should_use_tools` to true only when data, traces, news, or backtests are actually needed.
4. Set `requires_trace_save` to true for formal advice / formal weekly report / formal approval material.
5. `route_reason` should be short and concrete, stating the basis of the classification.
6. When the request is ambiguous, prefer the task closest to the user's direct goal over the broader generic.
"""
    return with_lang(prompt, output_language)
