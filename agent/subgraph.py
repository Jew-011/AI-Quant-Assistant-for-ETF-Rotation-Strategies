import concurrent.futures as _futures
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from agent.state import AgentState
from agent.patterns.pattern_log import log_pattern_use
from agent.patterns.goal_monitor import init_goal_state, update_goal_progress
from agent.patterns.multi_agent import DebateInputs, run_debate_parallel
from agent.patterns.memory import memory_context_snippet
from tools.backtest_tools import run_backtest
from tools.data_tools import get_market_data
from tools.factor_tools import calc_factors_df
from tools.filter_tools import get_ic_overlay_config
from tools.mapping_tools import map_etf
from tools.news_tools import search_news_cn, get_macro_events
from tools.global_news_strategy import (
    global_news_query,
    supports_chinese_sector_news,
)
from tools.report_tools import generate_report
from tools.scoring_tools import score_quadrant_df
from tools.trace_tools import TRACE_DIR, get_decision_history, save_decision_trace


SubgraphRoute = Literal[
    "weekly_prepare",
    "trace_history",
    "backtest_compare",
    "conflict_check",
    "rm_explain",
    "rm_portfolio_prepare",
    "compliance_risk",
    "multi_agent_debate",
    "executor",
    "finalize",
]

# Quadrant labels are produced by score_quadrant_df and stored verbatim in
# the dataframe column "quadrant" — they are data keys, not display strings,
# and must stay in their original Chinese form. The English gloss is added
# at presentation time only (see QUADRANT_LABEL_EN below).
QUADRANT_ORDER = ["黄金配置区", "左侧观察区", "高危警示区", "垃圾规避区"]
QUADRANT_LABEL_EN = {
    "黄金配置区": "Golden Zone",
    "左侧观察区": "Left-side Watch Zone",
    "高危警示区": "High-risk Warning Zone",
    "垃圾规避区": "Avoidance Zone",
}
TASK_ROUTE_MAP: dict[str, SubgraphRoute] = {
    "research_weekly_report": "weekly_prepare",
    "compliance_trace_review": "trace_history",
    "research_backtest_compare": "backtest_compare",
    "research_conflict_check": "conflict_check",
    "rm_explain_performance": "rm_explain",
    "rm_client_portfolio": "rm_portfolio_prepare",
    "compliance_risk_check": "compliance_risk",
    "research_multi_agent_debate": "multi_agent_debate",
}
SUBGRAPH_EDGE_MAP = {route: route for route in TASK_ROUTE_MAP.values()}
SUBGRAPH_EDGE_MAP.update({"executor": "executor", "finalize": "finalize"})


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _date_range(days: int) -> tuple[str, str]:
    end_date = _today()
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return start_date, end_date


def _stringify_tool_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def _safe_invoke_tool(tool_obj, payload: dict) -> str:
    try:
        return _stringify_tool_result(tool_obj.invoke(payload))
    except Exception as exc:
        return f"Tool error: {exc}"


def _latest_trace_file() -> str:
    if not os.path.isdir(TRACE_DIR):
        return ""

    latest_path = ""
    latest_mtime = -1.0
    for date_folder in sorted(os.listdir(TRACE_DIR), reverse=True):
        folder = os.path.join(TRACE_DIR, date_folder)
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            if not (fname.startswith("trace_") and fname.endswith(".json")):
                continue
            path = os.path.join(folder, fname)
            mtime = os.path.getmtime(path)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = path
    return latest_path


def _extract_keywords(text: str, max_keywords: int = 3) -> list[str]:
    normalized = text or ""
    for separator in ["，", ",", " ", "；", ";", "\n", "、"]:
        normalized = normalized.replace(separator, "|")

    unique_keywords: list[str] = []
    for word in (part.strip() for part in normalized.split("|")):
        if len(word) < 2 or word in unique_keywords:
            continue
        unique_keywords.append(word)
        if len(unique_keywords) >= max_keywords:
            break
    return unique_keywords


def _split_items(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[，,；;、/\n]+", raw or "") if item.strip()]


def _extract_code(text: str) -> str:
    match = re.search(r"\b(\d{6})\b", text or "")
    return match.group(1) if match else "-"


def _parse_overlay_text(overlay_text: str) -> tuple[dict[str, list[str]], list[str]]:
    observation_pool = {"export_chain": [], "policy_chain": [], "defensive": []}
    veto_list: list[str] = []
    current_section = ""
    active_veto = False

    for raw_line in overlay_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            label = line[1:-1]
            if "出口" in label:
                current_section = "export_chain"
                active_veto = False
            elif "政策" in label:
                current_section = "policy_chain"
                active_veto = False
            elif "防守" in label or "防御" in label:
                current_section = "defensive"
                active_veto = False
            else:
                current_section = ""
                active_veto = "(ACTIVE)" in label
            continue

        if line.startswith("Industries:"):
            industries = _split_items(line.split(":", 1)[1])
            if current_section:
                observation_pool[current_section].extend(industries)
            elif active_veto:
                veto_list.extend(industries)

    for key, values in observation_pool.items():
        observation_pool[key] = list(dict.fromkeys(values))
    veto_list = list(dict.fromkeys(veto_list))
    return observation_pool, veto_list


def _parse_mapping_text(
    mapping_text: str,
    offensive_industries: list[str] | None = None,
    allocation_industries: list[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    offensive_set = set(offensive_industries or [])
    allocation_set = set(allocation_industries or [])
    portfolio = {"offensive_layer": [], "allocation_layer": [], "defensive_layer": []}

    for raw_line in mapping_text.splitlines():
        line = raw_line.strip()
        if not line or " -> " not in line:
            continue

        sector, remainder = line.split(" -> ", 1)
        status_match = re.search(r"\[(PASS|FAIL)\]", remainder)
        detail_match = re.search(r"\(([^()]*)\)(?:\s+\|\s+Alternatives:.*)?$", remainder)
        etf_text = remainder[: status_match.start()].strip() if status_match else remainder.strip()
        rationale_parts = []
        if status_match:
            rationale_parts.append(f"liquidity filter {status_match.group(1)}")
        if detail_match:
            rationale_parts.append(detail_match.group(1).strip())

        row = {
            "sector": sector.strip(),
            "weight": "-",
            "etf": etf_text or "(to be confirmed)",
            "code": _extract_code(etf_text),
            "rationale": "; ".join(part for part in rationale_parts if part) or "ETF mapping result",
        }

        if row["sector"] in offensive_set:
            portfolio["offensive_layer"].append(row)
        elif row["sector"] in allocation_set:
            portfolio["allocation_layer"].append(row)
        else:
            portfolio["allocation_layer"].append(row)

    return portfolio


def _summarize_quadrants(quadrant_df) -> tuple[dict[str, list[str]], str]:
    quadrant_key_map = {
        "黄金配置区": "golden_zone",
        "左侧观察区": "left_side_zone",
        "高危警示区": "high_risk_zone",
        "垃圾规避区": "garbage_zone",
    }
    quadrant_distribution: dict[str, list[str]] = {}
    summary_lines = []
    for label in QUADRANT_ORDER:
        items = quadrant_df[quadrant_df["quadrant"] == label]["industry"].tolist()
        quadrant_distribution[quadrant_key_map[label]] = items
        preview = ", ".join(items[:8]) if items else "(none)"
        en_label = QUADRANT_LABEL_EN.get(label, label)
        summary_lines.append(f"- {en_label} / {label} ({len(items)}): {preview}")
    return quadrant_distribution, "\n".join(summary_lines)


def _concat_sections(*sections: str) -> str:
    return "\n\n".join(section for section in sections if section)


def _bump_tool_count(state: AgentState, increment: int) -> int:
    return state.get("tool_call_count", 0) + increment


def _log_node(node_name: str, message: str, level: str = "INFO") -> None:
    print(f"[subgraph][{node_name}][{level}] {message}", flush=True)


def _log_step(node_name: str, step: int, total: int, message: str) -> None:
    _log_node(node_name, f"step {step}/{total}: {message}")


def route_after_planner(state: AgentState) -> SubgraphRoute:
    if not state.get("should_use_tools", True):
        return "finalize"
    return TASK_ROUTE_MAP.get(state.get("task_key", "generic"), "executor")


def weekly_prepare_node(state: AgentState):
    market = state.get("market", "a_share")
    start_date, end_date = _date_range(days=365)
    _log_node(
        "weekly_prepare",
        f"building weekly-report skeleton, market={market}, range={start_date}~{end_date}",
    )

    _log_step("weekly_prepare", 1, 5, "fetch market data summary")
    market_data_summary = _safe_invoke_tool(
        get_market_data,
        {"market": market, "start_date": start_date, "end_date": end_date},
    )
    _log_node("weekly_prepare", "step 1/5 done")

    _log_step("weekly_prepare", 2, 5, "compute sector factors")
    factor_df = calc_factors_df(market=market, start_date=start_date, end_date=end_date)
    if factor_df.empty:
        _log_node(
            "weekly_prepare",
            "step 2/5 failed: no valid factor data",
            level="WARN",
        )
        return {
            "workflow_context": (
                "Fixed weekly-report subgraph failed: no valid factor data."
            ),
            "task_payload": {},
            "stop_reason": "Weekly-report subgraph received no valid factor data.",
        }
    _log_node(
        "weekly_prepare",
        f"step 2/5 done: {len(factor_df)} sector-level factor rows",
    )

    factor_summary = factor_df[
        ["industry", "trend_score", "consensus_score"]
    ].sort_values("trend_score", ascending=False).to_string(index=False)

    _log_step("weekly_prepare", 3, 5, "assign four-quadrant scores")
    quadrant_df = score_quadrant_df(factor_df)
    quadrant_distribution, quadrant_summary = _summarize_quadrants(quadrant_df)
    _log_node("weekly_prepare", "step 3/5 done")

    _log_step("weekly_prepare", 4, 5, "load observation pool and veto list")
    overlay_text = _safe_invoke_tool(get_ic_overlay_config, {"market": market})
    _log_node("weekly_prepare", "step 4/5 done")
    preferred_industries = quadrant_df[
        quadrant_df["quadrant"].isin(["黄金配置区", "左侧观察区"])
    ]["industry"].head(6).tolist()
    offensive_industries = quadrant_df[quadrant_df["quadrant"] == "黄金配置区"]["industry"].head(3).tolist()
    allocation_industries = quadrant_df[quadrant_df["quadrant"] == "左侧观察区"]["industry"].head(3).tolist()
    etf_mapping_text = (
        _safe_invoke_tool(
            map_etf,
            {"industries": ",".join(preferred_industries), "market": market},
        )
        if preferred_industries
        else "(no eligible sectors to map)"
    )
    _log_node(
        "weekly_prepare",
        f"step 5/5 done: ETF mapping candidates = {len(preferred_industries)} sectors",
    )
    observation_pool, veto_list = _parse_overlay_text(overlay_text)
    portfolio_recommendation = _parse_mapping_text(
        etf_mapping_text,
        offensive_industries=offensive_industries,
        allocation_industries=allocation_industries,
    )

    payload = {
        "decision_date": end_date,
        "market": market,
        "data_period": f"{start_date} to {end_date}",
        "quadrant_distribution": quadrant_distribution,
        "observation_pool_filter": observation_pool,
        "veto_list_exclusions": veto_list,
        "portfolio_recommendation": portfolio_recommendation,
        "factor_summary": factor_summary,
        "config_version": "fixed-workflow-v1",
        "timestamp": end_date,
        "approval_status": "pending",
    }
    workflow_context = _concat_sections(
        "## Fixed subgraph: research weekly-report skeleton",
        f"- Market: {market}\n- Data range: {start_date} to {end_date}",
        "### Market-data summary\n" + market_data_summary,
        "### Factor summary (sorted by trend score)\n" + factor_summary,
        "### Four-quadrant distribution\n" + quadrant_summary,
        "### Observation pool & veto list\n" + overlay_text,
        "### Candidate ETF mapping\n" + etf_mapping_text,
    )
    return {
        "workflow_context": workflow_context,
        "task_payload": payload,
        "tool_call_count": _bump_tool_count(state, 5),
        "stop_reason": "",
    }


def weekly_persist_node(state: AgentState):
    payload = dict(state.get("task_payload", {}))
    workflow_context = state.get("workflow_context", "")
    _log_node("weekly_persist", "rendering weekly-report template preview")
    report_preview = _safe_invoke_tool(
        generate_report,
        {
            "report_data": json.dumps(payload, ensure_ascii=False, indent=2),
            "template_type": "weekly_report",
            "role": state.get("role", "researcher"),
            "lang": state.get("output_language") or "zh",
        },
    )
    _log_node("weekly_persist", "template preview generated")

    save_result = "Decision Trace was not requested for this run."
    if state.get("requires_trace_save", False) and payload:
        _log_node("weekly_persist", "saving Decision Trace")
        save_result = _safe_invoke_tool(
            save_decision_trace,
            {"trace_json": json.dumps(payload, ensure_ascii=False)},
        )
        _log_node("weekly_persist", "Decision Trace saved")
    else:
        _log_node("weekly_persist", "trace save not requested", level="WARN")

    return {
        "workflow_context": _concat_sections(
            workflow_context,
            "### Weekly-report template preview\n" + report_preview,
            "### Trace save result\n" + save_result,
        )
    }


def trace_history_node(state: AgentState):
    _log_step("trace_history", 1, 2, "load decision-trace history (last 7 days)")
    history_text = _safe_invoke_tool(get_decision_history, {"days": 7})
    _log_step("trace_history", 2, 2, "locate the latest trace file")
    latest_path = _latest_trace_file()
    if not latest_path:
        _log_node("trace_history", "no trace file available for review", level="WARN")
        return {
            "workflow_context": (
                "## Fixed subgraph: compliance trace review\n"
                "No trace file is available for review."
            ),
            "latest_trace_path": "",
            "task_payload": {},
            "stop_reason": "No recent trace available for review.",
        }
    _log_node("trace_history", f"latest trace located: {latest_path}")

    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: compliance trace review",
            "### Trace overview (last 7 days)\n" + history_text,
        ),
        "latest_trace_path": latest_path,
        "stop_reason": "",
    }


def trace_review_node(state: AgentState):
    latest_path = state.get("latest_trace_path", "")
    workflow_context = state.get("workflow_context", "")
    if not latest_path or not os.path.isfile(latest_path):
        _log_node(
            "trace_review",
            "latest trace file missing; cannot continue review",
            level="WARN",
        )
        return {
            "workflow_context": _concat_sections(
                workflow_context,
                "Latest trace file not found; cannot continue review.",
            ),
            "stop_reason": "Latest trace file missing.",
        }

    _log_node("trace_review", f"reviewing trace: {latest_path}")
    with open(latest_path, "r", encoding="utf-8") as file_obj:
        trace = json.load(file_obj)

    required_keys = [
        "decision_date",
        "market",
        "quadrant_distribution",
        "portfolio_recommendation",
        "risk_checks",
        "config_version",
        "approval_status",
    ]
    missing_keys = [key for key in required_keys if key not in trace]
    present_keys = [key for key in required_keys if key in trace]
    review_lines = [
        f"- Latest trace path: {latest_path}",
        f"- Present required fields: {', '.join(present_keys) if present_keys else '(none)'}",
        f"- Missing required fields: {', '.join(missing_keys) if missing_keys else '(none)'}",
        f"- Approval status: {trace.get('approval_status', 'N/A')}",
        f"- Data date: {trace.get('decision_date', trace.get('timestamp', 'N/A'))}",
    ]
    if "risk_checks" in trace:
        review_lines.append(
            f"- Risk-check summary: {json.dumps(trace.get('risk_checks'), ensure_ascii=False)}"
        )
    if "quadrant_distribution" in trace:
        review_lines.append(
            f"- Four-quadrant summary: {json.dumps(trace.get('quadrant_distribution'), ensure_ascii=False)}"
        )
    _log_node(
        "trace_review",
        f"review complete: {len(missing_keys)} missing field(s)",
    )

    return {
        "workflow_context": _concat_sections(
            workflow_context,
            "### Latest trace — detailed review\n" + "\n".join(review_lines),
            "### Latest trace — raw content\n" + json.dumps(trace, ensure_ascii=False, indent=2),
        ),
        "task_payload": trace,
    }


def backtest_compare_node(state: AgentState):
    """Pattern 3: Parallelization — run monthly + weekly backtests concurrently."""
    market = state.get("market", "a_share")
    thread_id = state.get("thread_id", "default")
    start_date, end_date = _date_range(days=730)
    _log_node(
        "backtest_compare",
        f"backtest comparison started (parallel), market={market}, range={start_date}~{end_date}",
    )
    log_pattern_use(
        thread_id, 3, "Parallelization", "backtest_compare", "fan_out monthly+weekly"
    )

    freqs = [("monthly", "monthly rebalance"), ("weekly", "weekly rebalance")]
    results: dict[str, str] = {}
    with _futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(
                _safe_invoke_tool,
                run_backtest,
                {"market": market, "start_date": start_date, "end_date": end_date, "rebalance_freq": freq},
            ): freq
            for freq, _ in freqs
        }
        for fut in _futures.as_completed(futures):
            freq = futures[fut]
            results[freq] = fut.result()
            _log_node("backtest_compare", f"{freq} backtest done")

    monthly, weekly = results.get("monthly", ""), results.get("weekly", "")
    _log_node("backtest_compare", "backtest comparison complete (parallel)")
    payload = {
        "market": market,
        "start_date": start_date,
        "end_date": end_date,
        "monthly": monthly,
        "weekly": weekly,
        "executed_in_parallel": True,
    }
    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: backtest parameter comparison (research_backtest_compare, parallel)",
            f"- Market: {market}\n- Range: {start_date} to {end_date}",
            "### Monthly backtest result\n" + monthly,
            "### Weekly backtest result\n" + weekly,
        ),
        "task_payload": payload,
        "tool_call_count": _bump_tool_count(state, 2),
    }


def conflict_check_node(state: AgentState):
    market = state.get("market", "a_share")
    start_date, end_date = _date_range(days=365)
    _log_step("conflict_check", 1, 3, "compute sector factors")
    factor_df = calc_factors_df(market=market, start_date=start_date, end_date=end_date)
    if factor_df.empty:
        _log_node("conflict_check", "no valid factor data", level="WARN")
        return {
            "workflow_context": (
                "Fixed conflict-check subgraph failed: factor frame is empty."
            ),
            "stop_reason": "Conflict check has no valid factor data.",
        }

    _log_step("conflict_check", 2, 3, "load observation pool and veto list")
    quadrant_df = score_quadrant_df(factor_df)
    golden = quadrant_df[quadrant_df["quadrant"] == "黄金配置区"]["industry"].head(3).tolist()
    overlay_text = _safe_invoke_tool(get_ic_overlay_config, {"market": market})
    _log_step(
        "conflict_check",
        3,
        3,
        f"validate focus-sector news (parallel), n={len(golden)}",
    )
    thread_id = state.get("thread_id", "default")
    if golden:
        log_pattern_use(
            thread_id, 3, "Parallelization", "conflict_check", f"fan_out news for {len(golden)} sectors"
        )
    news_parts: list[str] = [""] * len(golden)
    with _futures.ThreadPoolExecutor(max_workers=min(5, max(len(golden), 1))) as pool:
        futures = {
            pool.submit(_safe_invoke_tool, search_news_cn, {"keywords": ind, "limit": 5}): idx
            for idx, ind in enumerate(golden)
        }
        for fut in _futures.as_completed(futures):
            idx = futures[fut]
            try:
                news_parts[idx] = f"#### {golden[idx]}\n{fut.result()}"
            except Exception as exc:
                news_parts[idx] = f"#### {golden[idx]}\nerror: {exc}"
    _log_node("conflict_check", "signal-conflict check complete (parallel)")

    payload = {
        "market": market,
        "golden_industries": golden,
        "overlay": overlay_text,
        "news": news_parts,
    }
    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: signal conflict check (research_conflict_check)",
            (
                f"- Market: {market}\n"
                f"- Golden-zone candidates: "
                f"{', '.join(golden) if golden else '(none)'}"
            ),
            "### Observation pool / veto list\n" + overlay_text,
            "### Focus-sector news cross-check\n"
            + ("\n\n".join(news_parts) if news_parts else "(no sector to validate)"),
        ),
        "task_payload": payload,
        "tool_call_count": _bump_tool_count(state, 2 + len(golden)),
    }


def rm_explain_node(state: AgentState):
    _log_step("rm_explain", 1, 2, "load recent decision history")
    history = _safe_invoke_tool(get_decision_history, {"days": 14})
    keywords = _extract_keywords(state.get("user_input", ""), max_keywords=2)
    _log_step(
        "rm_explain",
        2,
        2,
        f"add related news, n_keywords={len(keywords)}",
    )
    news_chunks = []
    for keyword in keywords:
        _log_node("rm_explain", f"searching keyword: {keyword}")
        news_chunks.append(
            f"#### Keyword: {keyword}\n"
            f"{_safe_invoke_tool(search_news_cn, {'keywords': keyword, 'limit': 5})}"
        )
    _log_node("rm_explain", "RM performance-explanation context ready")

    payload = {"history": history, "keywords": keywords, "news": news_chunks}
    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: RM performance explanation (rm_explain_performance)",
            "### Recent decision history\n" + history,
            "### Related events\n"
            + (
                "\n\n".join(news_chunks)
                if news_chunks
                else "(no usable keyword extracted; news enrichment skipped)"
            ),
        ),
        "task_payload": payload,
        "tool_call_count": _bump_tool_count(state, 1 + len(news_chunks)),
    }


def rm_portfolio_prepare_node(state: AgentState):
    market = state.get("market", "a_share")
    start_date, end_date = _date_range(days=365)
    _log_step("rm_portfolio_prepare", 1, 3, "compute sector factors")
    factor_df = calc_factors_df(market=market, start_date=start_date, end_date=end_date)
    if factor_df.empty:
        _log_node("rm_portfolio_prepare", "no valid factor data", level="WARN")
        return {
            "workflow_context": (
                "Fixed RM-portfolio subgraph failed: no valid factors."
            ),
            "stop_reason": "RM portfolio task: factor frame empty.",
        }

    _log_step("rm_portfolio_prepare", 2, 3, "filter candidate sectors")
    quadrant_df = score_quadrant_df(factor_df)
    picks = quadrant_df[
        quadrant_df["quadrant"].isin(["黄金配置区", "左侧观察区"])
    ]["industry"].head(4).tolist()
    _log_step(
        "rm_portfolio_prepare",
        3,
        3,
        f"map ETFs, n_sectors={len(picks)}",
    )
    mapped = (
        _safe_invoke_tool(map_etf, {"industries": ",".join(picks), "market": market})
        if picks
        else "(no eligible sectors to map)"
    )
    _log_node("rm_portfolio_prepare", "RM portfolio recommendation ready")
    risk_level = state.get("client_risk_level") or "not provided (defaulting to neutral)"
    payload = {
        "market": market,
        "risk_level": risk_level,
        "industries": picks,
        "mapped": mapped,
    }
    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: RM client portfolio (rm_client_portfolio)",
            (
                f"- Market: {market}\n"
                f"- Client risk level: {risk_level}\n"
                f"- Candidate sectors: "
                f"{', '.join(picks) if picks else '(none)'}"
            ),
            "### ETF mapping result\n" + mapped,
        ),
        "task_payload": payload,
        "tool_call_count": _bump_tool_count(state, 2),
    }


def rm_portfolio_persist_node(state: AgentState):
    payload = dict(state.get("task_payload", {}))
    workflow_context = state.get("workflow_context", "")
    if not (state.get("requires_trace_save", False) and payload):
        _log_node(
            "rm_portfolio_persist",
            "trace save not requested",
            level="WARN",
        )
        return {"workflow_context": workflow_context}

    _log_node("rm_portfolio_persist", "saving RM portfolio trace")
    trace = {
        "decision_date": _today(),
        "market": payload.get("market", state.get("market", "a_share")),
        "portfolio_recommendation": _parse_mapping_text(payload.get("mapped", ""), allocation_industries=payload.get("industries", [])),
        "risk_level": payload.get("risk_level", "not provided"),
        "industries": payload.get("industries", []),
        "config_version": "fixed-workflow-v1",
        "approval_status": "pending",
    }
    save_result = _safe_invoke_tool(
        save_decision_trace,
        {"trace_json": json.dumps(trace, ensure_ascii=False)},
    )
    _log_node("rm_portfolio_persist", "RM portfolio trace saved")
    return {
        "workflow_context": _concat_sections(
            workflow_context,
            "### Trace save result\n" + save_result,
        )
    }


def compliance_risk_node(state: AgentState):
    _log_step("compliance_risk", 1, 2, "locate the latest trace")
    latest_path = _latest_trace_file()
    if not latest_path or not os.path.isfile(latest_path):
        _log_node("compliance_risk", "no trace available for review", level="WARN")
        return {
            "workflow_context": (
                "## Fixed subgraph: compliance risk check\n"
                "No trace available for review."
            ),
            "stop_reason": "Risk check has no trace input.",
        }

    _log_step("compliance_risk", 2, 2, f"load and review trace: {latest_path}")
    with open(latest_path, "r", encoding="utf-8") as file_obj:
        trace = json.load(file_obj)

    risk_checks = trace.get("risk_checks", {})
    concentration = risk_checks.get("concentration_risk", "not provided")
    liquidity = risk_checks.get("liquidity_risk", "not provided")
    macro = risk_checks.get("macro_risks", [])
    sector = risk_checks.get("sector_risks", [])
    missing = [
        key for key in ["risk_checks", "portfolio_recommendation", "approval_status"] if key not in trace
    ]

    # Embed the FULL trace JSON in the workflow context so the downstream LLM
    # can quote it directly. Without this, the LLM only sees a short summary
    # and (correctly) refuses to issue a real compliance verdict, telling the
    # user "no trace_*.json was provided" -- which is confusing because the
    # file does exist on disk. Truncate to ~12 KB to stay well under any
    # context budget.
    try:
        trace_json_str = json.dumps(trace, ensure_ascii=False, indent=2)
    except Exception:
        trace_json_str = str(trace)
    if len(trace_json_str) > 12000:
        trace_json_str = trace_json_str[:12000] + "\n... (trace truncated for context budget)"

    _log_node(
        "compliance_risk",
        f"risk check complete; {len(missing)} required field(s) missing",
    )
    return {
        "workflow_context": _concat_sections(
            "## Fixed subgraph: compliance risk check (compliance_risk_check)",
            (
                f"- Reviewed trace: `{latest_path}`\n"
                f"- Approval status: {trace.get('approval_status', 'N/A')}\n"
                f"- Concentration risk: {concentration}\n"
                f"- Liquidity risk: {liquidity}\n"
                f"- Macro risks: {'; '.join(macro) if macro else '(none)'}\n"
                f"- Sector risks: {'; '.join(sector) if sector else '(none)'}\n"
                f"- Missing required fields: "
                f"{', '.join(missing) if missing else '(none)'}"
            ),
            "### Full trace JSON (authoritative review object)",
            "```json\n" + trace_json_str + "\n```",
        ),
        "task_payload": trace,
    }


def fetch_debate_evidence(
    market: str,
    sector_kw: str,
) -> tuple[str, str, dict[str, int]]:
    """Fetch macro events + sector news for the Multi-Agent Debate.

    This is the SAME logic the LangGraph multi_agent_debate_node uses,
    extracted so the standalone Streamlit Debate page can reuse it instead
    of feeding empty strings to the Macro specialist.

    Returns
    -------
    macro_events : str
        Concatenated Markdown sections (Domestic flash / Macro-theme /
        Global news), or a placeholder line when every source is empty.
    news_text : str
        Per-sector news payload appropriate for the market (CN sector
        news for A-share; English Alpha Vantage feed for US / HK).
    stats : dict
        Diagnostics: {'blocks': N, 'macro_events_len': N, 'news_len': N}.
    """
    global_kw, _global_topics = global_news_query(market, sector_kw)
    use_cn_sector_news = supports_chinese_sector_news(market)

    try:
        from tools.news_tools import search_news as _search_global_news  # type: ignore
    except Exception:
        _search_global_news = None

    with _futures.ThreadPoolExecutor(max_workers=4) as pool:
        fut_macro_cn = pool.submit(_safe_invoke_tool, get_macro_events, {})
        fut_macro_kw = pool.submit(
            _safe_invoke_tool,
            search_news_cn,
            {"keywords": "宏观 央行 货币政策 财政 地缘", "limit": 6},
        )
        if use_cn_sector_news:
            fut_news_sector = pool.submit(
                _safe_invoke_tool,
                search_news_cn,
                {"keywords": sector_kw, "limit": 8},
            )
        else:
            fut_news_sector = None

        if _search_global_news is not None:
            global_limit = 10 if not use_cn_sector_news else 6
            fut_news_global = pool.submit(
                _safe_invoke_tool,
                _search_global_news,
                {
                    "keywords": global_kw,
                    "source": "alphavantage",
                    "limit": global_limit,
                },
            )
        else:
            fut_news_global = None

        raw_macro_cn = fut_macro_cn.result() or ""
        raw_macro_kw = fut_macro_kw.result() or ""
        news_sector = fut_news_sector.result() if fut_news_sector else ""
        raw_global = fut_news_global.result() if fut_news_global else ""

    def _is_useful(txt: str) -> bool:
        t = (txt or "").strip()
        if len(t) < 40:
            return False
        low = t.lower()
        for neg in ("未找到", "暂无", "error", "未配置", "not found", "no data"):
            if neg in low:
                return False
        return True

    macro_blocks: list[str] = []
    if _is_useful(raw_macro_cn):
        macro_blocks.append("### Domestic macro flash (Jin10 / AKShare)\n" + raw_macro_cn)
    if _is_useful(raw_macro_kw):
        macro_blocks.append("### Macro-theme news (policy / central bank / geopolitics)\n" + raw_macro_kw)
    if _is_useful(raw_global) and use_cn_sector_news:
        macro_blocks.append("### Global financial news (Alpha Vantage)\n" + raw_global)

    if macro_blocks:
        macro_events = "\n\n".join(macro_blocks)
    else:
        macro_events = (
            "(All four macro sources returned empty just now; "
            "please reason conservatively from the observation pool and veto list.)"
        )

    if use_cn_sector_news:
        news_text = news_sector or ""
    else:
        news_text = raw_global or ""

    return macro_events, news_text, {
        "blocks": len(macro_blocks),
        "macro_events_len": len(macro_events),
        "news_len": len(news_text),
    }


def multi_agent_debate_node(state: AgentState):
    """Pattern 7 + 15 + 17: Multi-Agent Debate with structured messages & self-consistency.

    Three specialists (Quant/Macro/Risk) debate in parallel, a Coordinator
    resolves conflicts using self-consistency voting.
    """
    market = state.get("market", "a_share")
    thread_id = state.get("thread_id", "default")
    start_date, end_date = _date_range(days=365)

    _log_step("multi_agent_debate", 1, 4, "evidence prep — compute factors")
    factor_df = calc_factors_df(market=market, start_date=start_date, end_date=end_date)
    if factor_df.empty:
        return {
            "workflow_context": (
                "## Fixed subgraph: multi-agent debate\n"
                "No valid factor data; debate cannot proceed."
            ),
            "stop_reason": "Multi-agent debate has no factor data.",
        }

    _log_step("multi_agent_debate", 2, 4, "evidence prep — quadrants + overlay + macro")
    quadrant_df = score_quadrant_df(factor_df)
    _, quadrant_summary = _summarize_quadrants(quadrant_df)
    factor_summary = factor_df.head(10).to_string(index=False)
    overlay_text = _safe_invoke_tool(get_ic_overlay_config, {"market": market})
    observation_pool, veto_list = _parse_overlay_text(overlay_text)
    observation_text = json.dumps(observation_pool, ensure_ascii=False, indent=2)
    veto_text = "; ".join(veto_list) if veto_list else "(none)"

    # Macro evidence — four-way parallel scrape (Pattern 3).
    # Sector keywords still need to be joined for the Chinese news search;
    # commas keep them readable without coupling to a Chinese-only separator.
    golden = quadrant_df[quadrant_df["quadrant"] == "黄金配置区"]["industry"].head(4).tolist()
    sector_kw = ", ".join(golden[:3]) if golden else market

    macro_events, news_text, _stats = fetch_debate_evidence(
        market=market, sector_kw=sector_kw,
    )
    if _stats["blocks"] == 0:
        _log_node(
            "multi_agent_debate",
            "all 4 macro sources empty; Macro agent will rely on observation pool / veto list",
            level="WARN",
        )

    _log_node(
        "multi_agent_debate",
        f"evidence ready: factor={len(factor_summary)} chars, "
        f"quadrant={len(quadrant_summary)} chars, "
        f"macro={len(macro_events)} chars (blocks={len(macro_blocks)}), "
        f"news={len(news_text)} chars",
    )

    _log_step(
        "multi_agent_debate",
        3,
        4,
        "run Quant / Macro / Risk specialists (parallel)",
    )
    user_question = state.get("user_input", "")
    output_lang = state.get("output_language") or "en"
    debate_inputs = DebateInputs(
        market=market,
        factor_summary=factor_summary,
        quadrant_summary=quadrant_summary,
        observation_pool=observation_text,
        veto_list_text=veto_text,
        macro_events=macro_events,
        news_text=news_text,
        client_risk_level=state.get("client_risk_level"),
        user_question=user_question,
        output_language=output_lang,
    )
    model = os.getenv("OPENAI_MODEL", "deepseek-v3.2")
    # Heterogeneous ensemble: each specialist may run on a different model
    # (env vars set by the Settings page). Falls back to OPENAI_MODEL.
    models_per_role = {
        "quant": os.getenv("OPENAI_MODEL_QUANT") or model,
        "macro": os.getenv("OPENAI_MODEL_MACRO") or model,
        "risk":  os.getenv("OPENAI_MODEL_RISK")  or model,
    }
    coordinator_model = os.getenv("OPENAI_MODEL_COORDINATOR") or model
    debate_result = run_debate_parallel(
        debate_inputs,
        thread_id=thread_id,
        model=model,
        models_per_role=models_per_role,
        coordinator_model=coordinator_model,
    )

    _log_step(
        "multi_agent_debate",
        4,
        4,
        "Coordinator aggregation done; narrative produced",
    )
    verdict = debate_result["verdict"]
    narrative = verdict.get("narrative", "")
    recommended = verdict.get("recommended_sectors", [])
    vetoed = verdict.get("vetoed_sectors", [])
    disagreements = verdict.get("disagreements", [])

    debate_md_lines = [
        "## Fixed subgraph: multi-agent debate (research_multi_agent_debate)",
        (
            f"- Market: {market}  / "
            f"Client risk: {state.get('client_risk_level') or 'N/A'}"
        ),
        f"- Recommended (overweight): {', '.join(recommended) if recommended else '(none)'}",
        f"- Unanimously vetoed: {', '.join(vetoed) if vetoed else '(none)'}",
        f"- Disagreements: {len(disagreements)}",
        "",
        "### Specialist report summaries",
    ]
    for role, rep in debate_result["reports"].items():
        debate_md_lines.append(
            f"- **{role}** — {rep.get('summary', '')[:220]}"
        )
        for v in rep.get("votes", [])[:5]:
            debate_md_lines.append(
                f"  - {v['sector']}: {v['stance']} (conf={v['confidence']:.2f}) — {v['rationale'][:100]}"
            )
    if disagreements:
        debate_md_lines.append("\n### Disagreements and resolution")
        for d in disagreements[:10]:
            pro = ", ".join(d.get("agents_pro", []))
            con = ", ".join(d.get("agents_con", []))
            debate_md_lines.append(
                f"- **{d['sector']}**: pro={pro or '(none)'} / "
                f"con={con or '(none)'} → {d.get('resolution', '')}"
            )
    debate_md_lines.append("\n### Coordinator narrative\n" + narrative)

    payload = {
        "market": market,
        "client_risk_level": state.get("client_risk_level"),
        "debate": debate_result,
        "recommended_sectors": recommended,
        "vetoed_sectors": vetoed,
        "factor_summary": factor_summary,
    }
    return {
        "workflow_context": "\n".join(debate_md_lines),
        "task_payload": payload,
        "debate_result": debate_result,
        "tool_call_count": _bump_tool_count(state, 5),
    }


SUBGRAPH_NODES: dict[str, Callable[[AgentState], dict[str, Any]]] = {
    "weekly_prepare": weekly_prepare_node,
    "weekly_persist": weekly_persist_node,
    "trace_history": trace_history_node,
    "trace_review": trace_review_node,
    "backtest_compare": backtest_compare_node,
    "conflict_check": conflict_check_node,
    "rm_explain": rm_explain_node,
    "rm_portfolio_prepare": rm_portfolio_prepare_node,
    "rm_portfolio_persist": rm_portfolio_persist_node,
    "compliance_risk": compliance_risk_node,
    "multi_agent_debate": multi_agent_debate_node,
}


def register_subgraph_nodes(graph):
    for node_name, node_fn in SUBGRAPH_NODES.items():
        graph.add_node(node_name, node_fn)
