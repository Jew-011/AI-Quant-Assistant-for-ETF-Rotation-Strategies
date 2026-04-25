"""
Pattern 17: Reasoning (Self-Consistency).

When the Coordinator must resolve a conflict between specialist agents, we
sample the Coordinator LLM ``N`` times with non-zero temperature and take the
majority vote. This is a classic implementation of Wang et al. 2022
("Self-Consistency Improves CoT"). The voting log is persisted so auditors can
see the full reasoning distribution.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from agent.patterns.pattern_log import log_pattern_use


def self_consistency_vote(
    *,
    thread_id: str,
    prompt: str,
    llm_invoke: Callable[[str], Any],       # returns a pydantic model instance
    extract_choice: Callable[[Any], str],   # how to extract the voteable key
    samples: int = 3,
    temperature_hint: float = 0.7,
) -> dict:
    """
    Run the same reasoning prompt ``samples`` times and pick the majority answer.

    Returns:
        {
            "chosen": <the majority choice>,
            "chosen_sample": <the full model output that produced it>,
            "distribution": {choice: count, ...},
            "samples_raw": [sample1, sample2, ...]   # truncated
        }
    """
    log_pattern_use(
        thread_id,
        17,
        "Reasoning (Self-Consistency)",
        "self_consistency_vote",
        f"samples={samples}",
    )
    results: list[Any] = []
    for i in range(samples):
        try:
            results.append(llm_invoke(prompt))
        except Exception as exc:
            log_pattern_use(
                thread_id,
                17,
                "Reasoning (Self-Consistency)",
                "sample_failed",
                f"sample {i}: {exc}",
            )

    if not results:
        return {"chosen": None, "distribution": {}, "samples_raw": []}

    choices = [extract_choice(r) for r in results]
    counter = Counter(choices)
    chosen_value, _ = counter.most_common(1)[0]
    chosen_sample = next(r for r, c in zip(results, choices) if c == chosen_value)

    log_pattern_use(
        thread_id,
        17,
        "Reasoning (Self-Consistency)",
        "vote_resolved",
        f"winner={chosen_value} dist={dict(counter)}",
    )

    return {
        "chosen": chosen_value,
        "chosen_sample": chosen_sample,
        "distribution": dict(counter),
        "samples_raw": [str(r)[:500] for r in results],
    }
