from typing import Dict


TASK_PROMPTS: Dict[str, str] = {
    "generic": """## Task overlay: Generic
When the user intent does not match any high-frequency template, follow this:
1. First decide whether the goal is research, advisory, or compliance review.
2. Call only the tools strictly required to complete the task.
3. State your reasoning, risk warnings, and any open items.
""",
    "research_weekly_report": """## Task overlay: Research weekly report / rotation review
Applies to: weekly / daily report, sector-rotation summary, market scan.

Recommended flow:
1. `get_market_data` — fetch recent market data.
2. `calc_factors` — compute trend and consensus factors.
3. `score_quadrant` — assign sectors to the four quadrants.
4. `get_ic_overlay_config` — pull observation pool + veto list and apply the subjective filter.
5. Cross-check only the high-priority sectors with `search_news_cn` or `search_news`.
6. `map_etf` — translate sector picks into investable ETFs.
7. If the user asks for formal material, call `generate_report` and `save_decision_trace`.

Output should include:
- Four-quadrant distribution
- Observation-pool / veto explanation
- ETF portfolio recommendation
- Risk warnings
- (Optional) research summary or report skeleton when relevant
""",
    "research_overlay_adjustment": """## Task overlay: Observation-pool / veto-list adjustment + re-run
Applies to: add to observation pool, remove from veto list, re-run, compare before vs after.

Recommended flow:
1. Confirm which rule, sector, or config the user wants to change.
2. If a historical comparison is needed, call `get_decision_history` for the previous result.
3. Re-run market scan, factor calc, and quadrant scoring.
4. Use the observation pool / veto list to explain which sectors are kept or removed.
5. Output a "before vs after" change summary.

Output focus:
- Which config changed
- Which sectors / ETFs changed as a result
- Why the change happened
""",
    "research_backtest_compare": """## Task overlay: Parameter tuning + backtest comparison
Applies to: changing momentum window, factor weights, thresholds; backtest comparison.

Recommended flow:
1. Confirm the parameter sets to compare.
2. Generate signals (or read inputs) for each parameter set.
3. Use `run_backtest` to compare historical performance.
4. Report return, Sharpe, max drawdown, stability, and which regime each variant suits.

Output focus:
- Parameter comparison table
- Pros / cons across the headline metrics
- Whether the new parameters are worth adopting
""",
    "research_conflict_check": """## Task overlay: Signal conflict check
Applies to: do quantitative signals conflict with the veto list / news / observation pool?

Recommended flow:
1. Identify high-scoring or focus sectors.
2. Call `get_ic_overlay_config` for the observation pool and veto rules.
3. For conflicting sectors, validate with `search_news_cn` / `search_news`.
4. Output the conflict points, the evidence, and the recommended action.

Output focus:
- Which sectors conflict
- Whether the conflict comes from a rule or from news
- Final action: keep, downgrade, or remove
""",
    "rm_client_portfolio": """## Task overlay: Client-suitable portfolio + talking points
Applies to: which portfolio fits this client's risk level; produce client talking points.

Recommended flow:
1. Identify the client risk level. If missing, state your default assumption or ask the user to fill it in.
2. Build an ETF candidate list from the current market signals.
3. Adjust position sizes and tone to match the suitability and risk constraints.
4. Output client-friendly talking points, the rationale, risk warnings, and items to monitor.

Output focus:
- A portfolio suitable for this client
- A concise rationale
- Client-facing talking points
- Uncertainty and risk disclosure
""",
    "rm_explain_performance": """## Task overlay: Explain prior recommendation performance
Applies to: why did it drop, why did it rise, how do I explain to the client?

Recommended flow:
1. Call `get_decision_history` to read the previous trace.
2. Compare current vs previous sectors, quadrants, news flow, and risks.
3. Add news / market lookups only when extra facts are needed.
4. Output: what happened, why, current view, and how to explain it to the client.

Output focus:
- Previous recommendation vs current change
- Driver factors
- How to explain it to the client
- Whether to keep holding or move to observation
""",
    "rm_batch_talking_points": """## Task overlay: Batch client talking points
Applies to: many clients across many risk levels, batch-produce communication material.

Recommended flow:
1. Identify the client list and each client's risk level.
2. From a single market view, adjust emphasis per risk level.
3. Use a uniform template so the front-line team can ship quickly.

Output focus:
- A concise recommendation per client
- A bespoke talking-point script
- Risk warnings
""",
    "rm_market_specific": """## Task overlay: Client recommendation restricted to a specific market
Applies to: clients who only trade HK ETFs, only A-share, only US, etc.

Recommended flow:
1. Restrict the sector and ETF universe strictly to the chosen market.
2. Note how the market boundary affects the conclusion.
3. Provide a concise recommendation in client language plus risk warnings.
""",
    "compliance_trace_review": """## Task overlay: Decision Trace review
Applies to: pull the current trace, inspect the full decision chain, audit completeness.

Recommended flow:
1. Use `get_decision_history` to fetch recent traces.
2. Verify the trace contains timestamps, config version, factor results, quadrants, veto details, portfolio, risk checks.
3. Output the audit conclusion, missing items, and whether approval can proceed.

Output focus:
- Whether the trace is complete
- Whether the key fields are present
- What additional material is missing
""",
    "compliance_risk_check": """## Task overlay: Risk / compliance check
Applies to: does the portfolio breach risk rules, concentration limits, or liquidity requirements?

Recommended flow:
1. Pull the current portfolio and related risk fields.
2. Check single-ETF weight, sector concentration, cash buffer, liquidity, etc.
3. If evidence is insufficient, explicitly say the review cannot be completed.

Output focus:
- pass / fail / conditional pass
- Breaches or risk hot-spots
- Recommended remediation
""",
    "compliance_veto_audit": """## Task overlay: Vetoed-sector audit
Applies to: which sectors got vetoed this period; is the rationale sufficient?

Recommended flow:
1. Pull the current or most recent trace.
2. Cross-check the vetoes against the observation pool and the veto list.
3. Flag any sector whose justification is thin and needs more evidence.

Output focus:
- List of vetoed sectors
- The matching rule or rationale
- Whether the evidence is sufficient
""",
    "compliance_drawdown_check": """## Task overlay: Backtest drawdown + historical risk
Applies to: worst-case monthly drawdown, max historical drawdown, tail-risk discussion.

Recommended flow:
1. Reuse existing backtest results if available.
2. Otherwise call `run_backtest` for the historical performance.
3. Output max drawdown, the period it occurred, latent risk exposure, and the approval recommendation.
""",
}


TASK_SUMMARIES: Dict[str, str] = {
    "generic": "Generic task — used when the request does not match any high-frequency template.",
    "research_weekly_report": "Generate a weekly / daily sector-rotation report or market scan.",
    "research_overlay_adjustment": "Re-run after editing the observation pool or veto list and compare the change.",
    "research_backtest_compare": "Backtest comparison after parameter, window, or weight changes.",
    "research_conflict_check": "Check whether quantitative signals conflict with the observation pool, veto list, or news.",
    "rm_client_portfolio": "Produce an ETF portfolio recommendation + talking points for a given client risk level.",
    "rm_explain_performance": "Explain why the prior recommendation rose or fell and how to communicate it to the client.",
    "rm_batch_talking_points": "Batch-produce uniform-template talking points across multiple clients.",
    "rm_market_specific": "Generate a client recommendation restricted to a single market (HK only, US only, etc.).",
    "compliance_trace_review": "Pull and review the current or recent Decision Trace.",
    "compliance_risk_check": "Check whether the portfolio breaches risk rules, concentration limits, or liquidity requirements.",
    "compliance_veto_audit": "Audit the sectors vetoed this period and whether the rationale is sufficient.",
    "compliance_drawdown_check": "Inspect historical max drawdown, worst monthly drawdown, and tail risk.",
}


# Keyword routing: keep the original Chinese trigger words AND add their English
# equivalents so the rule-based fallback works for both UI languages.
ROLE_TASK_MAP = {
    "researcher": [
        ("research_backtest_compare", [
            "回测", "sharpe", "最大回撤", "参数", "窗口", "权重", "对比",
            "backtest", "drawdown", "parameter", "window", "weight", "compare",
        ]),
        ("research_overlay_adjustment", [
            "观察池", "负面清单", "否决", "移除", "加入", "重跑", "重新跑",
            "observation pool", "veto", "remove", "add", "rerun", "re-run",
        ]),
        ("research_conflict_check", [
            "冲突", "分歧", "一致", "否命中", "负面消息", "利空",
            "conflict", "disagree", "consensus", "negative news",
        ]),
        ("research_weekly_report", [
            "周报", "日报", "本周", "行业轮动", "市场扫描",
            "weekly", "daily report", "this week", "sector rotation", "market scan",
        ]),
    ],
    "rm": [
        ("rm_batch_talking_points", [
            "批量", "5个客户", "多个客户", "客户列表",
            "batch", "multiple clients", "client list",
        ]),
        ("rm_explain_performance", [
            "为什么跌", "为什么涨", "解释", "归因", "上周推荐",
            "why drop", "why rise", "explain", "attribution", "last week",
        ]),
        ("rm_market_specific", [
            "只要港股", "只要美股", "只要a股", "只看港股", "只看美股", "指定市场",
            "only hk", "only us", "only a-share", "only a share", "specific market",
        ]),
        ("rm_client_portfolio", [
            "客户", "风险等级", "r1", "r2", "r3", "r4", "r5", "话术", "组合",
            "client", "risk level", "talking point", "portfolio",
        ]),
    ],
    "compliance": [
        ("compliance_drawdown_check", [
            "回撤", "最差月度", "最大回撤", "drawdown",
            "max drawdown", "worst month",
        ]),
        ("compliance_veto_audit", [
            "否决", "剔除", "排除", "veto",
            "vetoed", "exclude",
        ]),
        ("compliance_risk_check", [
            "合规", "风控", "违反", "集中度", "流动性", "仓位上限",
            "compliance", "risk control", "breach", "concentration", "liquidity", "position limit",
        ]),
        ("compliance_trace_review", [
            "trace", "决策链", "审批", "审查", "留痕",
            "decision chain", "approval", "audit", "review",
        ]),
    ],
}


def get_allowed_task_keys_for_role(role: str) -> list[str]:
    role_keys = [task_key for task_key, _ in ROLE_TASK_MAP.get(role, [])]
    return role_keys + ["generic"]


def infer_task_key(user_input: str, role: str) -> str:
    text = (user_input or "").lower()
    for task_key, keywords in ROLE_TASK_MAP.get(role, []):
        if any(keyword in text for keyword in keywords):
            return task_key
    return "generic"


def get_task_prompt(task_key: str) -> str:
    return TASK_PROMPTS.get(task_key, TASK_PROMPTS["generic"])
