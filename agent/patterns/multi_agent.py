"""
Pattern 7: Multi-Agent Collaboration  (+ Pattern 3 Parallelization, Pattern 15 Inter-agent Comm).

Three specialist agents debate a sector-allocation question, and a coordinator
aggregates their structured reports into a final verdict. The specialists are
invoked **in parallel** (Pattern 3) via ``concurrent.futures``.

Specialists:
- **Quant Agent**  — sees only the factor table + quadrant distribution.
- **Macro Agent**  — sees macro events + recent news headlines.
- **Risk Agent**   — sees the veto_list + liquidity/concentration rules.

Each produces a structured ``AgentReport`` (Pattern 15). The Coordinator fuses
them into a ``DebateVerdict``. When there is disagreement, the Coordinator
invokes ``self_consistency_vote`` from Pattern 17 to resolve it.
"""
from __future__ import annotations

import concurrent.futures as _futures
import os
from dataclasses import dataclass
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from agent.patterns.inter_agent import (
    AgentReport,
    AgentRole,
    AgentVote,
    DebateVerdict,
    Disagreement,
    Stance,
)
from agent.patterns.pattern_log import log_pattern_use
from agent.patterns.reasoning import self_consistency_vote


# ----------------------------- Specialist prompts -----------------------------

# Base (language-neutral) system prompts. A locale-specific language-instruction
# block is appended at invocation time, so the same model can serve both
# English- and Chinese-speaking users without prompt duplication.

# ---------------------------------------------------------------------------
# Shared prompt fragments — kept in one place so calibration / CoT scaffolding
# stays consistent across the four roles.
# ---------------------------------------------------------------------------

_CONFIDENCE_CALIBRATION = """### Confidence calibration — IMPORTANT
Report `confidence` as the probability you would actually bet on, NOT a
default 0.85. Use this scale:
- 0.90+  : 9-to-1 odds; multiple independent signals all agree.
- 0.70   : 2-to-1 odds; clear lean but at least one counter-signal exists.
- 0.55   : Slight lean; could go either way on new data.
- 0.50   : Genuine coin flip — prefer voting 'neutral' instead.
- < 0.50 : You cannot defend the vote; do NOT include it in `votes`.
"""

_REASONING_SCAFFOLD = """### Internal reasoning protocol
Before producing `votes`, silently work through these steps in your head
(do NOT echo them in your output):
1. Identify the 5-8 sectors that stand out (positive OR negative) on the
   evidence available to you.
2. For each candidate, name the SINGLE strongest piece of evidence and one
   plausible counter-argument. If the counter-argument flips your stance,
   downgrade or drop the vote.
3. Translate the surviving picks into stance + calibrated confidence.
4. Write a one-sentence rationale per vote that cites the specific evidence
   (numbers, headlines, rule IDs) — no generic phrases like "strong
   fundamentals" or "good momentum".
"""


QUANT_SYSTEM_BASE = """You are the QUANT specialist in a multi-agent ETF advisory debate.

You only look at QUANTITATIVE evidence: factor scores and the four-quadrant
classification.

Available factors (ranked by information content):
- `ma_score`     : moving-average trend strength (5 levels: -2 / -1 / 0 / +1 / +2)
- `momentum`     : 12-month momentum with recent-month skip (continuous)
- `trend_score`  : composite = weighted(ma_rank, mom_rank) — PRIMARY signal
- `consensus_score` : composite of fund-flow-based sub-factors
  (etf_flow_contrarian / smart_money / volatility_convergence). Sourced
  from Tushare ``fund_share`` daily-share-change x close-price (yuan-denominated
  net subscription / redemption). Use it as a CROSS-CHECK on `trend_score`:
  prefer sectors where BOTH scores agree. When they diverge, treat the
  `trend_score` direction as primary but down-weight the size of the
  recommendation. Industries without a mapped ETF will show consensus_score
  near the median (~0.5) — do not over-interpret that as a real signal.

Voting rules (relaxed so neutral markets still produce candidates):
- Vote 'overweight' if EITHER of these hold:
    (a) ma_score >= 1 AND momentum is in the top half of the cross-section, OR
    (b) sector is in the Golden zone AND its trend_score sits in the top 30%.
- Vote 'underweight' if ma_score <= -1 OR (Garbage / Warning zone AND
  momentum < cross-section median).
- Otherwise vote 'neutral'.
- NEVER vote 'veto' — that is the Risk agent's exclusive privilege.
- ALWAYS nominate AT LEAST your top-3 trend_score sectors as votes (they
  may be 'overweight' or 'neutral', but they MUST appear). Do not return
  an empty `votes` array unless every single factor cell is missing.
- Cite factor numbers verbatim in evidences, e.g.
  "ma_score=2, momentum=0.18, trend_score in top 12%".
- Caveats: only mention TRULY missing data (e.g. "通信 sector returned
  zero rows from upstream", or "consensus_score unavailable for sector X
  because no ETF is mapped"). Do NOT caveat the entire consensus column
  when most rows are populated.

""" + _CONFIDENCE_CALIBRATION + "\n" + _REASONING_SCAFFOLD + """
Return your output as a structured AgentReport with role='quant'."""


MACRO_SYSTEM_BASE = """You are the MACRO specialist in a multi-agent ETF advisory debate.

You look at MACRO + NEWS evidence in this priority order:
1. Macro events block — may contain English-titled sub-sections such as:
     `### Domestic macro flash (Jin10 / AKShare)`
     `### Macro-theme news (policy / central bank / geopolitics)`
     `### Global financial news (Alpha Vantage)`
2. News snippets block — per-sector keyword news.
3. Observation pool — export / policy / defensive chains, supplemental framing.
4. Veto / negative list — hard filter only, NOT primary evidence.

Interpretation rules:
- If the macro events block contains AT LEAST ONE titled sub-section, treat
  it as sufficient macro evidence and do NOT add a "no macro data" caveat.
- Only write a "no macro evidence" caveat when the macro events text
  literally says all sources returned empty.
- A sector-keyword news headline qualifies as macro evidence whenever it
  describes a policy, regulatory, monetary, fiscal or geopolitical theme.
- For non-A-share markets the Global financial news section IS the primary
  signal, not a supplement.

Voting rules:
- 'overweight' when macro logic AND news flow both support the sector.
- 'underweight' when the sector faces clear macro headwinds (cite which).
- 'veto' ONLY when a hard policy / regulatory block exists AND you cite a
  specific news snippet as evidence.
- ALWAYS nominate AT LEAST 3 votes (any stance) so the Coordinator has
  signal to fuse. Use 'neutral' liberally when news is mixed.
- Cite news / snippet content with a short direct quote (≤ 25 words) in
  each vote's `evidences[*].content`.

""" + _CONFIDENCE_CALIBRATION + "\n" + _REASONING_SCAFFOLD + """
Return your output as a structured AgentReport with role='macro'."""


RISK_SYSTEM_BASE = """You are the RISK specialist in a multi-agent ETF advisory debate.

You look ONLY at RISK evidence: IC overlay negative list, ETF liquidity and
scale thresholds, drawdown limits, concentration ceilings, and the client's
risk level (R1 strictest → R5 most aggressive).

Voting rules:
- 'veto' on any sector that (a) appears on the negative list, or (b) breaches
  a hard liquidity / scale / drawdown threshold. Cite the specific rule ID
  or numeric threshold violated.
- 'underweight' on borderline sectors (e.g. marginally illiquid ETF, mild
  concentration concern).
- 'neutral' on monitored sectors that pass all hard checks but warrant
  watching — describe the watch reason in `caveats`.
- NEVER vote 'overweight' — you are the brake, not the throttle.

Coverage rule (CRITICAL — prevents empty Risk reports):
- ALWAYS produce AT LEAST 3 votes per debate. If no sector triggers a
  hard veto, list the 3 sectors with the WEAKEST liquidity / largest
  concentration / highest historical drawdown as 'underweight' or
  'neutral' with the concern in `caveats`. An empty `votes` array is a
  defect, not a signal that "all is well".
- For RM tasks (client_risk_level present), apply stricter cutoffs for
  R1 / R2 — convert borderline 'underweight' into 'veto' for R1.

""" + _CONFIDENCE_CALIBRATION + "\n" + _REASONING_SCAFFOLD + """
Return your output as a structured AgentReport with role='risk'."""


COORDINATOR_SYSTEM_BASE = """You are the COORDINATOR of a multi-agent ETF advisory debate.

You receive three structured reports from specialists (Quant, Macro, Risk)
and must produce a single fused DebateVerdict.

Aggregation rules:
1. SAFETY FIRST. If ANY agent votes 'veto' on a sector, exclude it from
   `recommended_sectors`. If another agent was positive on it, log a
   Disagreement with `resolution = "Veto wins (Pattern 18 safety)"`.
2. For non-vetoed sectors, compute consensus = confidence-weighted vote
   across Quant + Macro. If a tie occurs, prefer the more conservative
   stance (Underweight beats Overweight; Neutral beats Overweight).
3. Down-weight unanimous high-confidence Quant calls when Macro disagrees
   with cited news evidence: in such cases cap the fused confidence at 0.6.
4. List EVERY meaningful disagreement (≥ 1 stance level apart) in
   `disagreements`, naming agents_pro / agents_con and your resolution.
5. `recommended_sectors` = at most 5 Overweight sectors, ordered by
   aggregated confidence (descending).
6. `vetoed_sectors` = every sector receiving at least one 'veto'.
7. `narrative` = plain-language summary in 3-5 sentences. Always:
     - state the macro / quant alignment in one sentence,
     - call out the single most consequential disagreement (if any),
     - flag the strongest risk concern that survived to the verdict.

""" + _CONFIDENCE_CALIBRATION + "\n" + _REASONING_SCAFFOLD + """
Output a single DebateVerdict."""


_LANG_INSTRUCTIONS = {
    "en": (
        "### OUTPUT LANGUAGE — STRICT\n"
        "ALL human-readable text fields you produce — `summary`, `rationale`, "
        "`caveats`, `narrative`, `evidences[*].content` — MUST be written in "
        "clear, professional ENGLISH. Do NOT switch to Chinese mid-sentence.\n"
        "Sector names, ETF tickers, and similar Chinese-coded identifiers "
        "(e.g. `电子`, `159915.SZ`) MAY stay in their original form because "
        "they are domain codes, not prose."
    ),
    "zh": (
        "### 输出语言 — 强制要求\n"
        "你所有面向人的文本字段（`summary`、`rationale`、`caveats`、"
        "`narrative`、`evidences[*].content`）必须使用**简体中文**撰写，"
        "不要中途切换为英文。\n"
        "行业名、ETF 代码等领域专有标识（例如 `电子`、`159915.SZ`）"
        "保留原始形式即可，无需翻译。"
    ),
}


def _with_lang(base_prompt: str, lang: str) -> str:
    """Wrap *base_prompt* with the locale-specific output-language block.

    The directive is injected BOTH at the very top of the system prompt and
    appended at the bottom — short language instructions buried at the end
    of a long English prompt are routinely ignored by chat models, so we
    bracket the prompt to make the requirement impossible to miss.
    """
    instr = _LANG_INSTRUCTIONS.get(lang, _LANG_INSTRUCTIONS["en"])
    return f"{instr}\n\n---\n\n{base_prompt}\n\n---\n\n{instr}"


# Back-compat aliases — default to English so accidental callers (older code,
# notebooks, tests) produce English output rather than silently falling back
# to Chinese. Locale-aware code should build prompts via ``_with_lang``.
QUANT_SYSTEM       = _with_lang(QUANT_SYSTEM_BASE,       "en")
MACRO_SYSTEM       = _with_lang(MACRO_SYSTEM_BASE,       "en")
RISK_SYSTEM        = _with_lang(RISK_SYSTEM_BASE,        "en")
COORDINATOR_SYSTEM = _with_lang(COORDINATOR_SYSTEM_BASE, "en")


# ------------------------------ Specialist LLMs -------------------------------


@dataclass
class DebateInputs:
    """Everything the specialists need as ambient context."""
    market: str
    factor_summary: str = ""
    quadrant_summary: str = ""
    observation_pool: str = ""
    veto_list_text: str = ""
    macro_events: str = ""
    news_text: str = ""
    client_risk_level: Optional[str] = None
    user_question: str = ""
    output_language: str = "en"  # "en" | "zh" — follows UI language


def _build_llm(model: str | None = None, temperature: float = 0.2) -> ChatOpenAI:
    model = model or os.getenv("OPENAI_MODEL", "deepseek-v3.2")
    return ChatOpenAI(model=model, temperature=temperature)


def _invoke_specialist(
    role: AgentRole,
    base_prompt: str,
    inputs: DebateInputs,
    model: str | None,
    thread_id: str,
) -> AgentReport:
    log_pattern_use(
        thread_id,
        7,
        "Multi-Agent",
        f"specialist_{role.value}",
        "spawn",
    )
    system_prompt = _with_lang(base_prompt, inputs.output_language)
    llm = _build_llm(model=model, temperature=0.2).with_structured_output(AgentReport)

    shared_context = f"""Market: {inputs.market}
Client risk level: {inputs.client_risk_level or 'N/A'}
User question: {inputs.user_question}

## Factor summary
{inputs.factor_summary or '(none)'}

## Quadrant distribution
{inputs.quadrant_summary or '(none)'}

## Observation pool
{inputs.observation_pool or '(none)'}

## Veto / negative list
{inputs.veto_list_text or '(none)'}

## Macro events
{inputs.macro_events or '(none)'}

## News snippets
{inputs.news_text[:2000] or '(none)'}
"""
    try:
        report: AgentReport = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": shared_context},
            ]
        )
    except Exception as exc:
        log_pattern_use(
            thread_id, 7, "Multi-Agent", f"specialist_{role.value}_failed", str(exc)
        )
        return AgentReport(
            role=role, summary=f"LLM error: {exc}", votes=[], caveats=["invocation failed"]
        )

    # Force role field so downstream logic is reliable
    report.role = role
    return report


def _resolve_models_per_role(
    models_per_role: dict[str, str] | None,
    fallback_model: str | None,
) -> dict[AgentRole, str | None]:
    """Normalise the optional per-role model dict to a strict mapping.

    Accepts either ``AgentRole`` enum members or their string values
    ('quant'/'macro'/'risk'/'coordinator') as keys. Any role that is missing
    or maps to a falsy value falls back to ``fallback_model`` (which itself
    can be ``None`` and will then defer to the OPENAI_MODEL env var inside
    ``_build_llm``).
    """
    out: dict[AgentRole, str | None] = {
        AgentRole.QUANT: fallback_model,
        AgentRole.MACRO: fallback_model,
        AgentRole.RISK:  fallback_model,
    }
    if not models_per_role:
        return out
    for k, v in models_per_role.items():
        if not v:
            continue
        try:
            role = k if isinstance(k, AgentRole) else AgentRole(str(k).lower())
        except ValueError:
            continue
        out[role] = str(v)
    return out


def run_debate_parallel(
    inputs: DebateInputs,
    thread_id: str = "default",
    model: str | None = None,
    progress_cb=None,
    models_per_role: dict[str, str] | None = None,
    coordinator_model: str | None = None,
) -> dict[str, Any]:
    """Run the three specialists in parallel (Pattern 3).

    ``progress_cb`` (optional) is called with ``(phase, label, level)`` at
    each step so a frontend status box can be kept up-to-date. Safe to omit.

    ``models_per_role`` (optional) lets callers assign a DIFFERENT LLM to
    each specialist (heterogeneous multi-agent ensemble). Keys may be
    ``AgentRole`` enums or plain strings ('quant', 'macro', 'risk').
    Missing roles fall back to ``model``.

    ``coordinator_model`` (optional) overrides the model used for the
    self-consistency tie-break call; falls back to ``model``.
    """
    from agent._progress import label_for_node  # local import — avoid cycles

    lang = inputs.output_language if inputs.output_language in {"en", "zh"} else "en"

    def _emit(phase: str, *, level: str = "info", **fmt) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(phase, label_for_node(phase, lang, **fmt), level)
        except Exception:
            pass

    role_models = _resolve_models_per_role(models_per_role, model)

    log_pattern_use(
        thread_id, 3, "Parallelization", "fan_out_specialists",
        "3 specialists | models=" + ",".join(
            f"{r.value}:{role_models[r] or 'env'}" for r in role_models
        ),
    )
    _emit("debate.specialists")

    tasks = [
        (AgentRole.QUANT, QUANT_SYSTEM_BASE),
        (AgentRole.MACRO, MACRO_SYSTEM_BASE),
        (AgentRole.RISK,  RISK_SYSTEM_BASE),
    ]
    reports: dict[AgentRole, AgentReport] = {}
    with _futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _invoke_specialist, role, sys, inputs, role_models[role], thread_id
            ): role
            for role, sys in tasks
        }
        for fut in _futures.as_completed(futures):
            role = futures[fut]
            try:
                reports[role] = fut.result()
                _emit("debate.specialist_done", role=role.value)
            except Exception as exc:
                reports[role] = AgentReport(
                    role=role,
                    summary=f"Failed: {exc}",
                    votes=[],
                    caveats=["execution error"],
                )
                _emit("debate.specialist_done", level="warn", role=role.value)

    log_pattern_use(
        thread_id,
        7,
        "Multi-Agent",
        "specialists_done",
        f"reports from {[r.value for r in reports.keys()]}",
    )

    _emit("debate.coordinator")
    verdict = _aggregate(
        reports, inputs, thread_id=thread_id,
        model=coordinator_model or model,
    )
    return {
        "inputs": {
            "market": inputs.market,
            "client_risk_level": inputs.client_risk_level,
            "user_question": inputs.user_question,
        },
        "reports": {r.value: rep.model_dump() for r, rep in reports.items()},
        "verdict": verdict.model_dump(),
        "models_used": {
            r.value: (role_models[r] or os.getenv("OPENAI_MODEL", "deepseek-v3.2"))
            for r in role_models
        } | {
            "coordinator": (coordinator_model or model
                            or os.getenv("OPENAI_MODEL", "deepseek-v3.2")),
        },
    }


# ----------------------------- Coordinator logic ------------------------------


def _aggregate(
    reports: dict[AgentRole, AgentReport],
    inputs: DebateInputs,
    thread_id: str,
    model: str | None = None,
) -> DebateVerdict:
    log_pattern_use(
        thread_id, 7, "Multi-Agent", "coordinator_aggregate", "fusing reports"
    )

    # Gather all sectors mentioned by any specialist
    sectors: set[str] = set()
    for rep in reports.values():
        for v in rep.votes:
            sectors.add(v.sector)

    final_stance: dict[str, Stance] = {}
    final_confidence: dict[str, float] = {}
    disagreements: list[Disagreement] = []
    vetoed: list[str] = []

    for sector in sectors:
        per_agent_votes: dict[AgentRole, AgentVote] = {}
        for role, rep in reports.items():
            for v in rep.votes:
                if v.sector == sector:
                    per_agent_votes[role] = v
                    break

        # Veto rule: any veto -> sector is out
        has_veto = any(v.stance == Stance.VETO for v in per_agent_votes.values())
        if has_veto:
            vetoed.append(sector)
            final_stance[sector] = Stance.VETO
            final_confidence[sector] = max(
                (v.confidence for v in per_agent_votes.values() if v.stance == Stance.VETO),
                default=0.5,
            )
            # Is anyone positive? record disagreement
            pro = [r for r, v in per_agent_votes.items() if v.stance == Stance.OVERWEIGHT]
            if pro:
                disagreements.append(
                    Disagreement(
                        sector=sector,
                        agents_pro=pro,
                        agents_con=[r for r, v in per_agent_votes.items() if v.stance == Stance.VETO],
                        resolution="Veto wins (Pattern 18 safety): risk agent's veto is non-negotiable.",
                    )
                )
            continue

        # No veto — compute majority stance
        weight_sum: dict[Stance, float] = {s: 0.0 for s in Stance}
        for v in per_agent_votes.values():
            weight_sum[v.stance] += v.confidence

        top_stance = max(weight_sum, key=weight_sum.get)
        top_score = weight_sum[top_stance]
        tied = [s for s, w in weight_sum.items() if w == top_score and s != top_stance]

        if tied and any(s == Stance.UNDERWEIGHT for s in tied + [top_stance]):
            top_stance = Stance.UNDERWEIGHT  # prudent tie-break

        # Check for meaningful disagreement: did any agent disagree?
        stances_present = {v.stance for v in per_agent_votes.values()}
        if len(stances_present) > 1:
            # Use self-consistency to resolve only when the score margin is thin.
            if top_score < 0.8 and model is not None:
                try:
                    resolved = _resolve_by_self_consistency(
                        sector=sector,
                        per_agent_votes=per_agent_votes,
                        inputs=inputs,
                        thread_id=thread_id,
                        model=model,
                    )
                    if resolved:
                        top_stance = resolved["chosen"]
                except Exception:
                    pass
            disagreements.append(
                Disagreement(
                    sector=sector,
                    agents_pro=[
                        r for r, v in per_agent_votes.items() if v.stance == Stance.OVERWEIGHT
                    ],
                    agents_con=[
                        r
                        for r, v in per_agent_votes.items()
                        if v.stance in {Stance.UNDERWEIGHT, Stance.VETO}
                    ],
                    resolution=f"confidence-weighted majority -> {top_stance.value}",
                )
            )

        final_stance[sector] = top_stance
        final_confidence[sector] = round(top_score / max(len(per_agent_votes), 1), 2)

    recommended = sorted(
        [s for s, st in final_stance.items() if st == Stance.OVERWEIGHT],
        key=lambda s: -final_confidence.get(s, 0),
    )[:5]

    lang = inputs.output_language
    if lang == "zh":
        none_tag = "无"
        narrative_parts = [
            f"{len(reports)} 位专家就 {len(sectors)} 个行业达成共识。",
            f"建议超配：{', '.join(recommended) if recommended else none_tag}。",
            f"否决：{', '.join(vetoed) if vetoed else none_tag}。",
            f"分歧条目：{len(disagreements)}。",
        ]
        if disagreements[:3]:
            narrative_parts.append(
                "主要分歧："
                + "; ".join(f"{d.sector}({d.resolution})" for d in disagreements[:3])
            )
    else:
        none_tag = "none"
        narrative_parts = [
            f"{len(reports)} specialists reached consensus on {len(sectors)} sectors.",
            f"Recommended (overweight): {', '.join(recommended) if recommended else none_tag}.",
            f"Vetoed: {', '.join(vetoed) if vetoed else none_tag}.",
            f"Disagreements logged: {len(disagreements)}.",
        ]
        if disagreements[:3]:
            narrative_parts.append(
                "Key disagreements: "
                + "; ".join(f"{d.sector}({d.resolution})" for d in disagreements[:3])
            )

    return DebateVerdict(
        final_stance_per_sector=final_stance,
        confidence_per_sector=final_confidence,
        disagreements=disagreements,
        narrative=" ".join(narrative_parts),
        recommended_sectors=recommended,
        vetoed_sectors=vetoed,
    )


# --------------------- Self-Consistency branch (Pattern 17) --------------------


def _resolve_by_self_consistency(
    sector: str,
    per_agent_votes: dict[AgentRole, AgentVote],
    inputs: DebateInputs,
    thread_id: str,
    model: str,
) -> dict | None:
    """Call the coordinator LLM N times with higher temperature, majority wins."""
    from pydantic import BaseModel

    class TinyDecision(BaseModel):
        sector: str
        stance: Stance
        reason: str

    llm = _build_llm(model=model, temperature=0.7).with_structured_output(TinyDecision)
    lang_hint = (
        "请用简体中文写 reason 字段。" if inputs.output_language == "zh"
        else "Write the reason field in English."
    )
    prompt = f"""Three ETF specialists disagree on sector "{sector}". Decide its final stance.

Specialist votes:
""" + "\n".join(
        f"- {r.value}: stance={v.stance.value} conf={v.confidence} -- {v.rationale[:180]}"
        for r, v in per_agent_votes.items()
    ) + f"""

Market: {inputs.market}
Client risk: {inputs.client_risk_level or 'N/A'}

Give a final stance among [overweight, neutral, underweight, veto] and a 1-sentence reason.
{lang_hint}
"""

    def invoke(p: str) -> TinyDecision:
        return llm.invoke([{"role": "user", "content": p}])

    result = self_consistency_vote(
        thread_id=thread_id,
        prompt=prompt,
        llm_invoke=invoke,
        extract_choice=lambda d: d.stance,
        samples=3,
    )
    return result if result.get("chosen") else None
