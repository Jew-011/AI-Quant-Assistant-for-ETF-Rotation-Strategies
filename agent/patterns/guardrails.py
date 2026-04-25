"""
Pattern 18: Guardrails.

Three layers of guardrails (matching the course slide "Defense-in-depth"):

1. Input Guardrail (before execution)
   - Jailbreak/injection keyword detection
   - Out-of-scope query rejection (e.g. "buy 10M of X", "ignore previous instructions")
   - PII redaction (basic)

2. Output Guardrail (before side effects)
   - Compliance phrase filter ("guaranteed return", "必涨", "保证收益")
   - Financial suitability hedge enforcement
   - Must-include risk disclosure for portfolio outputs

3. HITL Approval Gate (before saving trace / releasing to client)
   - Formal deliverables require human approval (captured as pending status)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal

from agent.patterns.pattern_log import log_pattern_use

HITL_QUEUE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "traces", "hitl")
os.makedirs(HITL_QUEUE_DIR, exist_ok=True)


INPUT_BLOCK_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"忽略\s*(之前|以上)\s*(所有)?指令",
    r"你\s*现在\s*是\s*一个",
    r"system\s*prompt",
    r"api[_\s]?key",
    r"\.env",
    r"(real[_\s]?)?money\s+transfer",
    r"帮\s*我\s*(买|卖|下单|交易).{0,10}\d{4,}",
]

INPUT_WARN_PATTERNS = [
    r"\d{11,}",
    r"(身份证|银行卡|手机号)",
]

OUTPUT_BLOCK_PHRASES = [
    "保证收益",
    "必涨",
    "必跌",
    "稳赚不赔",
    "零风险",
    "guaranteed return",
    "risk-free",
    "definitely outperform",
]

# Portfolio-style outputs must contain at least one of these "risk warning"
# tokens. Both Chinese and English variants are checked because the LLM may
# answer in either language depending on output_language.
MUST_INCLUDE_WHEN_PORTFOLIO_ANY = [
    "风险",
    "risk",
]


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""
    risk_level: Literal["none", "low", "medium", "high"] = "none"
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def input_guardrail(user_input: str, thread_id: str = "default") -> GuardrailResult:
    """Pre-execution check. Blocks obvious prompt injection and out-of-scope ops."""
    log_pattern_use(
        thread_id,
        18,
        "Guardrails",
        "input_guardrail",
        f"Checking input len={len(user_input)}",
    )
    text = (user_input or "").strip()
    if not text:
        return GuardrailResult(False, "Empty input rejected", "low")

    if len(text) > 4000:
        return GuardrailResult(
            False,
            f"Input length {len(text)} exceeds the 4000-character cap",
            "medium",
        )

    lowered = text.lower()
    for pat in INPUT_BLOCK_PATTERNS:
        if re.search(pat, lowered, flags=re.IGNORECASE):
            return GuardrailResult(
                False,
                (
                    f"Input matched a blocked pattern: {pat}. "
                    "This agent only provides research / advisory / compliance support; "
                    "it does not execute real trades or follow injected system instructions."
                ),
                "high",
                {"matched_pattern": pat},
            )

    warns = [pat for pat in INPUT_WARN_PATTERNS if re.search(pat, text)]
    if warns:
        return GuardrailResult(
            True,
            (
                f"Possible sensitive data detected ({warns}). "
                "Allowed for now, but please avoid including personal data in queries."
            ),
            "medium",
            {"warn_patterns": warns},
        )

    return GuardrailResult(True, "ok", "none")


def output_guardrail(
    output_text: str, is_portfolio: bool, thread_id: str = "default"
) -> GuardrailResult:
    """Post-generation check. Blocks non-compliant claims and enforces risk disclosure."""
    log_pattern_use(
        thread_id,
        18,
        "Guardrails",
        "output_guardrail",
        f"Checking output, is_portfolio={is_portfolio}",
    )
    text = output_text or ""
    hits = [p for p in OUTPUT_BLOCK_PHRASES if p.lower() in text.lower()]
    if hits:
        return GuardrailResult(
            False,
            f"Output contains blocked phrases {hits}; cannot release to clients.",
            "high",
            {"blocked_phrases": hits},
        )

    if is_portfolio:
        # Pass if at least one of the required risk-disclosure tokens is present.
        if not any(kw.lower() in text.lower() for kw in MUST_INCLUDE_WHEN_PORTFOLIO_ANY):
            return GuardrailResult(
                False,
                (
                    "Portfolio-style output is missing the mandatory risk-warning section "
                    f"(expected one of {MUST_INCLUDE_WHEN_PORTFOLIO_ANY})."
                ),
                "medium",
                {"missing_keywords": MUST_INCLUDE_WHEN_PORTFOLIO_ANY},
            )

    return GuardrailResult(True, "ok", "none")


def redact_output(output_text: str) -> str:
    """If output fails the guardrail, replace blocked phrases with placeholders."""
    result = output_text or ""
    for p in OUTPUT_BLOCK_PHRASES:
        if p.lower() in result.lower():
            result = re.sub(re.escape(p), "[redacted]", result, flags=re.IGNORECASE)
    return result


def request_hitl_approval(
    thread_id: str,
    task_key: str,
    payload: dict,
    requester: str = "system",
) -> dict:
    """
    Create a pending HITL approval request.
    In production this would page a human; in the prototype we persist it to
    disk and return a reference ID so the frontend can surface it.
    """
    log_pattern_use(
        thread_id,
        18,
        "Guardrails",
        "hitl_approval",
        f"Creating HITL request for task={task_key}",
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    req_id = f"hitl_{task_key}_{ts}"
    record = {
        "id": req_id,
        "thread_id": thread_id,
        "task_key": task_key,
        "requester": requester,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
        "payload": payload,
        "decision": None,
        "decided_at": None,
        "decided_by": None,
        "comment": "",
    }
    path = os.path.join(HITL_QUEUE_DIR, f"{req_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def list_hitl_queue(status: str = "all") -> list[dict]:
    """Read all HITL approval records. Used by the frontend."""
    if not os.path.isdir(HITL_QUEUE_DIR):
        return []
    records = []
    for fn in sorted(os.listdir(HITL_QUEUE_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(HITL_QUEUE_DIR, fn), "r", encoding="utf-8") as f:
                rec = json.load(f)
            if status == "all" or rec.get("status") == status:
                records.append(rec)
        except Exception:
            continue
    return records


def decide_hitl(req_id: str, approved: bool, reviewer: str, comment: str = "") -> dict:
    """Called from the frontend approval page to record a decision."""
    path = os.path.join(HITL_QUEUE_DIR, f"{req_id}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"HITL request not found: {req_id}")
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    rec["status"] = "approved" if approved else "rejected"
    rec["decision"] = rec["status"]
    rec["decided_at"] = datetime.now().isoformat(timespec="seconds")
    rec["decided_by"] = reviewer
    rec["comment"] = comment
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec
