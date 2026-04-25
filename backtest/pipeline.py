"""
回测管道：在每个调仓日运行因子+四象限→生成信号→跑回测。
"""
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
import yaml

from tools.factor_tools import calc_factors_df
from tools.scoring_tools import score_quadrant_df

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
LOOKBACK_DAYS = 300  # 因子计算需足够历史数据（momentum 250 日）


def _load_etf_mapping() -> Dict[str, str]:
    """行业名 -> ETF 代码（primary）"""
    with open(os.path.join(CONFIG_DIR, "etf_mapping.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    mapping = {}
    for ind_name, entry in cfg.get("mapping", {}).items():
        code = entry.get("primary", {}).get("code", "")
        if code:
            mapping[ind_name] = code
    return mapping


def _get_provider(market: str):
    from tools.data_tools import _load_market_config, _get_provider as _gp
    cfg = _load_market_config(market)
    return _gp(cfg)


def _generate_rebalance_dates(start_date: str, end_date: str, freq: str) -> pd.DatetimeIndex:
    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    if freq == "monthly":
        dates = pd.date_range(s, e, freq="ME")
    else:
        dates = pd.date_range(s, e, freq="W-FRI")
    return dates


def run_backtest_pipeline(
    market: str = "a_share",
    start_date: str = "2023-01-01",
    end_date: str = "2025-01-01",
    rebalance_freq: str = "monthly",
    verbose: bool = True,
) -> dict:
    """
    完整回测流程：逐调仓日算因子+四象限 → 生成 industry_signals → 拉 ETF 价格 → 跑回测。

    Args:
        verbose: 是否打印实时进度

    Returns:
        dict with nav_series, metrics, trades, industry_signals (前几行示例)
    """
    from .runner import run_backtest

    industry_to_etf = _load_etf_mapping()
    provider = _get_provider(market)
    reb_dates = _generate_rebalance_dates(start_date, end_date, rebalance_freq)
    total = len(reb_dates)

    def _log(msg: str):
        if verbose:
            print(msg, flush=True)

    _log(f"[回测] 开始 | 市场={market} | {start_date}~{end_date} | 调仓={rebalance_freq} | 共 {total} 个调仓日")
    _log("-" * 50)

    signal_rows = []
    etf_codes_needed = set()

    for i, reb_dt in enumerate(reb_dates):
        reb_str = reb_dt.strftime("%Y-%m-%d")
        lookback_start = (reb_dt - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        _log(f"  [{i+1}/{total}] {reb_str} 算因子...")
        factor_df = calc_factors_df(market, lookback_start, reb_str)
        if factor_df.empty:
            _log(f"       (无数据，跳过)")
            continue

        quadrant_df = score_quadrant_df(factor_df)
        if quadrant_df.empty:
            continue

        quadrant_df["date"] = reb_str
        signal_rows.append(quadrant_df)

        golden = quadrant_df[quadrant_df["quadrant"] == "黄金配置区"]
        golden_names = golden["industry"].tolist()
        _log(f"       黄金区: {len(golden_names)} 个 → {', '.join(golden_names[:5])}{'...' if len(golden_names) > 5 else ''}")
        for ind in golden_names:
            if ind in industry_to_etf:
                etf_codes_needed.add(industry_to_etf[ind])

    if not signal_rows:
        return {
            "error": "无有效信号",
            "nav_series": pd.DataFrame(),
            "metrics": {},
            "trades": [],
            "industry_signals": pd.DataFrame(),
        }

    industry_signals = pd.concat(signal_rows, ignore_index=True)
    _log("-" * 50)
    _log(f"[回测] 拉取 ETF 价格 | 共 {len(etf_codes_needed)} 只: {', '.join(sorted(etf_codes_needed)[:8])}{'...' if len(etf_codes_needed) > 8 else ''}")

    etf_prices = {}
    for i, code in enumerate(etf_codes_needed):
        if i > 0:
            time.sleep(0.5)  # 避免 Tushare IP 超限
        df = provider.get_etf_daily(code, start_date, end_date)
        if not df.empty and "close" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            etf_prices[code] = df[["date", "close"]]
        if verbose and (i + 1) % 5 == 0:
            _log(f"      ETF 已拉 {i+1}/{len(etf_codes_needed)}")

    _log(f"[回测] 计算净值与指标...")
    result = run_backtest(
        industry_signals=industry_signals,
        etf_prices=etf_prices,
        rebalance_freq=rebalance_freq,
        start_date=start_date,
        end_date=end_date,
        industry_to_etf=industry_to_etf,
    )
    result["industry_signals"] = industry_signals.head(50)
    m = result.get("metrics", {})
    _log("-" * 50)
    _log(f"[回测] 完成 | 年化 {m.get('annualized_return', 0)*100:.2f}% | 最大回撤 {m.get('max_drawdown', 0)*100:.2f}% | 夏普 {m.get('sharpe_ratio', 0):.2f}")
    return result
