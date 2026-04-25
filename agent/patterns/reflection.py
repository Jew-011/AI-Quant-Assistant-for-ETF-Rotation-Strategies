"""
Pattern 4: Reflection (real critic -> revise loop).

The original code only injected a REFLECTION_PROMPT string. This module
implements a true reflection cycle:

1. ``critic_llm`` examines the draft answer and the available evidence.
2. It emits a structured ``CritiqueReport`` (pydantic) with a numerical score
   and a list of concrete issues.
3. If the score is below ``REVISE_THRESHOLD``, ``revise_draft`` re-invokes the
   main LLM with the critique as additional guidance, producing a revised
   answer.
4. The loop runs at most ``MAX_REFLECT_ROUNDS`` times. Each round is recorded
   into the trace so auditors can see what the agent changed and why.
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from agent.patterns.pattern_log import log_pattern_use

REVISE_THRESHOLD = 0.75
MAX_REFLECT_ROUNDS = 1


class CritiqueIssue(BaseModel):
    severity: str = Field(description="'critical' | 'major' | 'minor'")
    category: str = Field(
        description="quality aspect: factual / compliance / completeness / clarity / risk"
    )
    comment: str = Field(description="one-sentence description of the issue")
    suggestion: str = Field(description="how the revised draft should address it")


class CritiqueReport(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="overall quality score")
    passes_quality_bar: bool = Field(
        description="True if draft can be released without revision"
    )
    issues: list[CritiqueIssue] = Field(
        default_factory=list, description="problems worth fixing"
    )
    summary: str = Field(description="one-paragraph summary of the review")


def build_critic_prompt(
    user_input: str,
    role: str,
    task_key: str,
    draft_answer: str,
    workflow_context: str,
) -> str:
    return f"""You are a senior quality reviewer for an ETF advisory agent. Review the DRAFT answer below.

## Context
- User role: {role}
- Task: {task_key}
- User question: {user_input}

## Workflow evidence
{workflow_context or '(none)'}

## Draft answer
{draft_answer}

## Review dimensions (ALWAYS all 5)
1. **Factual grounding** — are claims backed by the workflow evidence? Any hallucinated numbers?
2. **Compliance safety** — any forbidden phrases ("guaranteed", "必涨"), missing risk disclosure, or suitability mismatch?
3. **Completeness** — does it address every part of the user's question and the expected deliverable for the task?
4. **Clarity & structure** — is it easy to scan? Proper markdown formatting? Distinguishes facts vs inferences vs risks?
5. **Risk framing** — does the text explicitly flag uncertainty, missing data, and key risks?

## Scoring
- 1.0 = release as-is
- 0.9 = tiny polish only
- 0.75 = minor issues, but no need to revise
- 0.5 = major issues — MUST revise
- 0.2 = unsafe / unusable — MUST revise

Return a structured critique. List at most 5 issues, most important first.
"""


def build_revise_prompt(
    original_draft: str,
    critique: CritiqueReport,
    workflow_context: str,
) -> str:
    issues_md = "\n".join(
        f"- [{i.severity.upper()}|{i.category}] {i.comment}  → fix: {i.suggestion}"
        for i in critique.issues
    )
    return f"""The previous draft received a critique with score {critique.score:.2f}.
Revise the draft so that it fully addresses every issue listed below. Keep the
structure and any correct content; change only what is needed.

## Previous draft
{original_draft}

## Critique summary
{critique.summary}

## Issues to fix
{issues_md or '(none)'}

## Workflow evidence (unchanged)
{workflow_context or '(none)'}

Output the REVISED answer only. Do not explain what you changed.
"""


def run_reflection(
    *,
    thread_id: str,
    user_input: str,
    role: str,
    task_key: str,
    draft_answer: str,
    workflow_context: str,
    critic_llm_invoke: Callable[[str], CritiqueReport],
    revise_llm_invoke: Callable[[str], str],
    max_rounds: int = MAX_REFLECT_ROUNDS,
) -> dict[str, Any]:
    """
    Execute the reflection loop. Returns:
        {
            "final_answer": str,        # best answer after reflection
            "rounds": [                 # each round's critique + revision
                {"round": 1, "critique": {...}, "revised": "..."},
                ...
            ],
            "reflected": bool,          # whether any revision was produced
        }
    """
    log_pattern_use(
        thread_id, 4, "Reflection", "run_reflection", f"start max_rounds={max_rounds}"
    )
    current = draft_answer
    rounds: list[dict[str, Any]] = []

    for r in range(1, max_rounds + 1):
        critic_prompt = build_critic_prompt(
            user_input, role, task_key, current, workflow_context
        )
        try:
            critique = critic_llm_invoke(critic_prompt)
        except Exception as exc:
            log_pattern_use(
                thread_id,
                4,
                "Reflection",
                "critic_failed",
                f"round {r}: {exc}",
            )
            break

        rounds.append({"round": r, "critique": critique.model_dump()})

        if critique.passes_quality_bar or critique.score >= REVISE_THRESHOLD:
            log_pattern_use(
                thread_id,
                4,
                "Reflection",
                "pass_quality_bar",
                f"round {r} score={critique.score:.2f}",
            )
            break

        revise_prompt = build_revise_prompt(current, critique, workflow_context)
        try:
            revised = revise_llm_invoke(revise_prompt)
        except Exception as exc:
            log_pattern_use(
                thread_id, 4, "Reflection", "revise_failed", f"round {r}: {exc}"
            )
            break

        rounds[-1]["revised"] = revised
        current = revised
        log_pattern_use(
            thread_id,
            4,
            "Reflection",
            "revised",
            f"round {r} score_before={critique.score:.2f}",
        )

    return {
        "final_answer": current,
        "rounds": rounds,
        "reflected": any("revised" in r for r in rounds),
    }
