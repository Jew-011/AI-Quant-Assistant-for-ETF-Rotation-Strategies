from agent.prompts._lang import output_language_instruction
from agent.prompts.base_prompt import BASE_SYSTEM_PROMPT
from agent.prompts.role_prompts import get_role_prompt
from agent.prompts.task_prompts import get_task_prompt, infer_task_key


def build_system_prompt(
    role: str,
    market: str,
    user_input: str,
    client_risk_level: str | None = None,
    output_language: str = "en",
) -> str:
    task_key = infer_task_key(user_input=user_input, role=role)

    runtime_context = [
        "## Runtime context",
        f"- Current role: {role}",
        f"- Current market: {market}",
        f"- Inferred task: {task_key}",
    ]
    if role == "rm":
        runtime_context.append(f"- Client risk level: {client_risk_level or 'not provided'}")

    market_context = """## Market constraint
- All analysis and recommendations must stay inside the current market. Do not mix markets unless the user explicitly asks for a cross-market comparison.
- If the current market lacks data or configuration, say so explicitly. Do not invent sectors or ETFs."""

    role_prompt = get_role_prompt(role)
    task_prompt = get_task_prompt(task_key)

    return "\n\n".join(
        [
            BASE_SYSTEM_PROMPT,
            "\n".join(runtime_context),
            market_context,
            role_prompt,
            task_prompt,
            output_language_instruction(output_language),
        ]
    )
