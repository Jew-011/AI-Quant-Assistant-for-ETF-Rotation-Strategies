import json
import os
import re
from datetime import datetime, timedelta


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_DIR = os.path.join(PROJECT_ROOT, "traces")
REPORT_WEEK_MODE = "last_complete_week"


def _parse_decision_datetime(trace: dict) -> tuple[str, datetime]:
    decision_date = (
        trace.get("decision_date")
        or trace.get("date")
        or trace.get("timestamp")
        or datetime.now().strftime("%Y-%m-%d")
    )
    try:
        dt = datetime.strptime(str(decision_date)[:10], "%Y-%m-%d")
        decision_date = dt.strftime("%Y-%m-%d")
    except Exception:
        decision_date = datetime.now().strftime("%Y-%m-%d")
        dt = datetime.now()
    return decision_date, dt


def format_report_week(dt: datetime, mode: str = REPORT_WEEK_MODE) -> str:
    if mode == "decision_week":
        start = dt - timedelta(days=dt.weekday())
        end = start + timedelta(days=6)
        iso = dt.isocalendar()
        return f"{dt.year}年第{iso[1]}周 ({start.month}月{start.day}日-{end.month}月{end.day}日)"

    if mode == "last_complete_week":
        start = dt - timedelta(days=dt.weekday() + 7)
        end = start + timedelta(days=6)
        iso = start.isocalendar()
        return f"{start.year}年第{iso[1]}周 ({start.month}月{start.day}日-{end.month}月{end.day}日)"

    raise ValueError(f"Unknown report week mode: {mode}")


def load_latest_trace(trace_dir: str = TRACE_DIR, for_date: str | None = None) -> tuple[dict | None, str | None]:
    folder = os.path.join(trace_dir, for_date or datetime.now().strftime("%Y-%m-%d"))
    if not os.path.isdir(folder):
        return None, None

    files = sorted(
        [f for f in os.listdir(folder) if f.endswith(".json") and f.startswith("trace_")],
        reverse=True,
    )
    if not files:
        return None, None

    path = os.path.join(folder, files[0])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


def load_trace(trace_path: str | None = None) -> tuple[dict, str, str]:
    if trace_path:
        with open(trace_path, "r", encoding="utf-8") as f:
            trace = json.load(f)
        return trace, trace_path, os.path.dirname(trace_path)

    trace, resolved_path = load_latest_trace()
    if not trace or not resolved_path:
        raise FileNotFoundError("未找到今日 trace，请指定路径")
    return trace, resolved_path, os.path.dirname(resolved_path)


def load_agent_response(trace_dir: str) -> str:
    path = os.path.join(trace_dir, "agent_response.txt")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "（无 Agent 回复记录）"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _split_items(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return _dedupe_keep_order([str(item) for item in raw if str(item).strip()])
    if isinstance(raw, str):
        parts = re.split(r"[，,；;、/\n]+", raw)
        return _dedupe_keep_order(parts)
    return []


def _extract_code(text: str) -> str:
    match = re.search(r"\b(\d{6})\b", text or "")
    return match.group(1) if match else "-"


def _normalize_observation_pool(trace: dict) -> dict:
    pool = trace.get("observation_pool_filter")
    if not pool:
        pool = trace.get("observation_pool_alignment", {})

    if isinstance(pool, str):
        normalized = {"export_chain": [], "policy_chain": [], "defensive": []}
        current_key = ""
        for raw_line in pool.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                label = line[1:-1]
                if "出口" in label:
                    current_key = "export_chain"
                elif "政策" in label:
                    current_key = "policy_chain"
                elif "防守" in label or "防御" in label:
                    current_key = "defensive"
                else:
                    current_key = ""
            elif line.startswith("Industries:") and current_key:
                normalized[current_key].extend(_split_items(line.split(":", 1)[1]))
        return {key: _dedupe_keep_order(value) for key, value in normalized.items()}

    if not isinstance(pool, dict):
        return {"export_chain": [], "policy_chain": [], "defensive": []}

    return {
        "export_chain": _split_items(pool.get("export_chain")),
        "policy_chain": _split_items(pool.get("policy_chain")),
        "defensive": _split_items(pool.get("defensive") or pool.get("defensive_core")),
    }


def _normalize_veto_list(trace: dict) -> list[str]:
    veto_list = trace.get("veto_list_exclusions", [])
    if isinstance(veto_list, list):
        if veto_list and isinstance(veto_list[0], dict):
            items = []
            for item in veto_list:
                industry = item.get("industry") or item.get("sector") or ""
                reason = item.get("reason") or item.get("description") or ""
                items.append(f"{industry}: {reason}" if industry and reason else industry or reason)
            return _dedupe_keep_order(items)
        return _dedupe_keep_order([str(item) for item in veto_list])

    veto_applied = trace.get("veto_applied", [])
    items = []
    for item in veto_applied:
        if not isinstance(item, dict):
            continue
        industry = item.get("industry") or item.get("sector") or ""
        reason = item.get("reason") or item.get("note") or item.get("veto_code") or ""
        items.append(f"{industry}: {reason}" if industry and reason else industry or reason)
    return _dedupe_keep_order(items)


def _normalize_portfolio_layers(layers: dict) -> dict:
    normalized = {"offensive_layer": [], "allocation_layer": [], "defensive_layer": []}
    layer_aliases = {
        "offensive_layer": ["offensive_layer", "aggressive_layer"],
        "allocation_layer": ["allocation_layer", "configuration_layer"],
        "defensive_layer": ["defensive_layer"],
    }

    for target_key, aliases in layer_aliases.items():
        source_items = []
        for alias in aliases:
            candidate = layers.get(alias, [])
            if isinstance(candidate, list) and candidate:
                source_items = candidate
                break

        for item in source_items:
            if not isinstance(item, dict):
                continue
            sector = item.get("sector") or item.get("industry") or ""
            if not sector:
                continue
            etf = item.get("etf") or item.get("etf_example") or "待确认"
            normalized[target_key].append(
                {
                    "sector": str(sector),
                    "weight": str(item.get("weight", "-")),
                    "etf": str(etf),
                    "code": str(item.get("code") or _extract_code(str(etf))),
                    "rationale": str(item.get("rationale", "-")),
                }
            )

    return normalized


def _parse_mapping_text(raw: str) -> dict:
    rows = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ": No ETF mapping found." in line:
            sector = line.split(":", 1)[0].strip()
            rows.append(
                {
                    "sector": sector,
                    "weight": "-",
                    "etf": "待确认",
                    "code": "-",
                    "rationale": "未找到 ETF 映射",
                }
            )
            continue
        if " -> " not in line:
            continue

        sector, remainder = line.split(" -> ", 1)
        status_match = re.search(r"\[(PASS|FAIL)\]", remainder)
        details_match = re.search(r"\(([^()]*)\)(?:\s+\|\s+Alternatives:.*)?$", remainder)
        etf_text = remainder[: status_match.start()].strip() if status_match else remainder.strip()
        rationale_parts = []
        if status_match:
            rationale_parts.append(f"流动性筛选 {status_match.group(1)}")
        if details_match:
            rationale_parts.append(details_match.group(1).strip())

        rows.append(
            {
                "sector": sector.strip(),
                "weight": "-",
                "etf": etf_text or "待确认",
                "code": _extract_code(etf_text),
                "rationale": "；".join(part for part in rationale_parts if part) or "ETF 映射结果",
            }
        )

    return {"offensive_layer": [], "allocation_layer": rows, "defensive_layer": []}


def _normalize_portfolio(trace: dict) -> dict:
    portfolio = trace.get("portfolio_recommendation")
    if isinstance(portfolio, dict):
        return _normalize_portfolio_layers(portfolio)
    if isinstance(portfolio, str):
        return _parse_mapping_text(portfolio)

    legacy_portfolio = trace.get("etf_portfolio", {})
    if isinstance(legacy_portfolio, dict):
        return _normalize_portfolio_layers(legacy_portfolio)

    return {"offensive_layer": [], "allocation_layer": [], "defensive_layer": []}


def _normalize_risk_checks(trace: dict) -> dict:
    risk_checks = trace.get("risk_checks")
    if isinstance(risk_checks, dict):
        return {
            "concentration_risk": risk_checks.get("concentration_risk", "见正文"),
            "liquidity_risk": risk_checks.get("liquidity_risk", "见正文"),
            "macro_risks": _split_items(risk_checks.get("macro_risks")),
            "sector_risks": _split_items(risk_checks.get("sector_risks")),
        }

    risk_controls = trace.get("risk_controls", {})
    if isinstance(risk_controls, dict):
        cash_reserve = risk_controls.get("cash_reserve")
        liquidity = f"现金留存 {cash_reserve}" if cash_reserve else "见正文"
        return {
            "concentration_risk": risk_controls.get("sector_concentration_limits", "见正文"),
            "liquidity_risk": liquidity,
            "macro_risks": _split_items(risk_controls.get("geopolitical_risk_monitoring")),
            "sector_risks": [],
        }

    return {
        "concentration_risk": "见正文",
        "liquidity_risk": "见正文",
        "macro_risks": [],
        "sector_risks": [],
    }


def _get_quadrant_lists(trace: dict) -> dict:
    qd = trace.get("quadrant_distribution", {})
    pr = _normalize_portfolio(trace)
    return {
        "golden": _dedupe_keep_order(
            qd.get("golden_zone")
            or qd.get("golden")
            or qd.get("黄金配置区")
            or [x.get("sector", "") for x in pr.get("offensive_layer", []) if x.get("sector")]
        ),
        "left": _dedupe_keep_order(
            qd.get("left_side_zone")
            or qd.get("leftside_zone")
            or qd.get("left_zone")
            or qd.get("左侧观察区")
            or [x.get("sector", "") for x in pr.get("allocation_layer", []) if x.get("sector")]
        ),
        "danger": _dedupe_keep_order(
            qd.get("high_risk_zone") or qd.get("danger_zone") or qd.get("danger") or qd.get("高危警示区") or []
        ),
        "garbage": _dedupe_keep_order(qd.get("garbage_zone") or qd.get("garbage") or qd.get("垃圾规避区") or []),
    }


def _get_etf_rows(trace: dict) -> tuple[list[dict], str]:
    pr = _normalize_portfolio(trace)
    rows: list[dict] = []
    for layer_name in ("offensive_layer", "allocation_layer", "defensive_layer"):
        for item in pr.get(layer_name, []):
            sector = item.get("sector")
            if not sector or sector in {"现金", "现金/货币基金"}:
                continue
            etf = item.get("etf", "待确认")
            code = item.get("code") or _extract_code(str(etf))
            rows.append(
                {
                    "sector": sector,
                    "etf": etf,
                    "code": code or "-",
                    "weight": str(item.get("weight", "-")),
                    "rationale": str(item.get("rationale", "-")),
                }
            )

    table = "\n".join(
        f"| {row['sector']} | {row['code']} | {row['weight']} | {row['rationale']} |"
        for row in rows
    )
    return rows, table or "| - | - | - | - |"


def _get_cash_reserve(trace: dict) -> str:
    pr = _normalize_portfolio(trace)
    cash = next(
        (
            x.get("weight", "10")
            for x in pr.get("defensive_layer", [])
            if x.get("sector") in {"现金", "现金/货币基金"}
        ),
        trace.get("risk_controls", {}).get("cash_reserve", "10"),
    )
    return str(cash).replace("%", "")


def _get_pool_description(observation_pool: dict) -> str:
    pool_parts = []
    if observation_pool.get("export_chain"):
        pool_parts.append(f"出口链: {', '.join(observation_pool['export_chain'])}")
    if observation_pool.get("policy_chain"):
        pool_parts.append(f"政策链: {', '.join(observation_pool['policy_chain'])}")
    if observation_pool.get("defensive"):
        pool_parts.append(f"防守: {', '.join(observation_pool['defensive'])}")
    return "；".join(pool_parts) if pool_parts else "见配置"


def _get_risk_warning_text(risk_checks: dict) -> str:
    risk_parts = []
    if risk_checks.get("concentration_risk"):
        risk_parts.append(str(risk_checks["concentration_risk"]))
    if risk_checks.get("liquidity_risk"):
        risk_parts.append(str(risk_checks["liquidity_risk"]))
    for risk in risk_checks.get("macro_risks", []):
        risk_parts.append(str(risk))
    for risk in risk_checks.get("sector_risks", []):
        risk_parts.append(str(risk))
    return "；".join(risk_parts) if risk_parts else "见正文"


def build_report_data(trace: dict) -> dict:
    decision_date, dt = _parse_decision_datetime(trace)
    quadrant = _get_quadrant_lists(trace)
    etf_rows, etf_table = _get_etf_rows(trace)
    observation_pool = _normalize_observation_pool(trace)
    risk_checks = _normalize_risk_checks(trace)
    veto_list = _normalize_veto_list(trace)

    return {
        "date": decision_date,
        "decision_date": decision_date,
        "report_week": format_report_week(dt),
        "data_timestamp": trace.get("data_period", trace.get("timestamp", decision_date)),
        "config_version": trace.get("config_version", trace.get("analysis_approach", "N/A")),
        "quadrant": quadrant,
        "golden_industries": "、".join(quadrant["golden"]) if quadrant["golden"] else "无",
        "left_side_industries": "、".join(quadrant["left"]) if quadrant["left"] else "无",
        "danger_industries": "、".join(quadrant["danger"]) if quadrant["danger"] else "无",
        "garbage_industries": "、".join(quadrant["garbage"]) if quadrant["garbage"] else "无",
        "observation_pool": observation_pool,
        "pool_description": _get_pool_description(observation_pool),
        "veto_list": veto_list,
        "veto_details": "\n".join(f"- {item}" for item in veto_list) if veto_list else "无",
        "etf_rows": etf_rows,
        "etf_table": etf_table,
        "cash_reserve": _get_cash_reserve(trace),
        "changes_vs_last": "（首次报告或无上期对比数据）",
        "risk_checks": risk_checks,
        "risk_warnings": _get_risk_warning_text(risk_checks),
        "news_validation": trace.get("news_validation", {}),
        "reasoning_chain": trace.get("reasoning_chain", "-"),
        "trace": trace,
    }
