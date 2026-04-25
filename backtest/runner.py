import pandas as pd
import numpy as np
from typing import Dict, Optional
from .portfolio import allocate_weights
from .metrics import calc_metrics

def run_backtest(
    industry_signals: pd.DataFrame,
    etf_prices: Dict[str, pd.DataFrame],
    rebalance_freq: str = "monthly",
    start_date: str = "2022-01-01",
    end_date: str = "2025-01-01",
    industry_to_etf: Dict[str, str] = None,
) -> dict:
    """
    Run a backtest over historical data.
    
    Args:
        industry_signals: DataFrame with columns [date, industry, quadrant, trend_score, consensus_score]
                          one row per industry per rebalance date
        etf_prices: dict mapping ETF code -> DataFrame with columns [date, close]
        industry_to_etf: optional dict mapping industry name -> ETF code (for return calculation)
        rebalance_freq: 'monthly' or 'weekly'
        start_date: backtest start
        end_date: backtest end
    
    Returns:
        dict with keys: nav_series (pd.Series), metrics (dict), trades (list)
    """
    # CRITICAL: normalise rebalance dates to "YYYY-MM-DD" strings so they match
    # the string dates stored in industry_signals["date"] and etf_prices[code]["date"].
    # Otherwise np.datetime64 vs str comparisons silently return False everywhere
    # and every period return collapses to 0.
    rebalance_dates_raw = _get_rebalance_dates(industry_signals["date"].unique(), rebalance_freq)
    rebalance_dates = [_normalize_date_str(d) for d in rebalance_dates_raw]

    nav = 1.0
    nav_series = []
    trades = []
    current_weights = {}

    for i, reb_date in enumerate(rebalance_dates):
        signals_at_date = industry_signals[industry_signals["date"] == reb_date]
        golden = signals_at_date[signals_at_date["quadrant"] == "黄金配置区"]

        if golden.empty:
            new_weights = {}
        else:
            new_weights = allocate_weights(golden, method="equal")

        if i > 0:
            prev_date = rebalance_dates[i - 1]
            weights_for_ret = _to_etf_weights(current_weights, industry_to_etf) if industry_to_etf else current_weights
            period_return = _calc_period_return(weights_for_ret, etf_prices, prev_date, reb_date)
            nav *= (1 + period_return)

        nav_series.append({"date": reb_date, "nav": nav})
        trades.append({"date": reb_date, "weights": new_weights.copy()})
        current_weights = new_weights

    if len(rebalance_dates) > 0:
        last_reb = rebalance_dates[-1]
        weights_for_ret = _to_etf_weights(current_weights, industry_to_etf) if industry_to_etf else current_weights
        final_return = _calc_period_return(weights_for_ret, etf_prices, last_reb, _normalize_date_str(end_date))
        nav *= (1 + final_return)
        nav_series.append({"date": _normalize_date_str(end_date), "nav": nav})

    nav_df = pd.DataFrame(nav_series)
    nav_df["date"] = pd.to_datetime(nav_df["date"])
    nav_df = nav_df.set_index("date")

    metrics = calc_metrics(nav_df["nav"])
    return {"nav_series": nav_df, "metrics": metrics, "trades": trades}


def _to_etf_weights(industry_weights: dict, industry_to_etf: dict) -> dict:
    """将行业权重视图转为 ETF 权重视图。未映射的行业跳过。"""
    out = {}
    for ind, w in industry_weights.items():
        etf = industry_to_etf.get(ind)
        if etf:
            out[etf] = w
    return out


def _get_rebalance_dates(all_dates, freq: str) -> np.ndarray:
    dates = pd.to_datetime(sorted(all_dates))
    if freq == "monthly":
        return dates[dates.to_series().dt.is_month_end | (dates == dates[-1])].values
    elif freq == "weekly":
        return dates[dates.to_series().dt.dayofweek == 4].values  # Fridays
    return dates.values


def _normalize_date_str(d) -> str:
    """Normalise any date-ish input (str / datetime / numpy.datetime64 / pd.Timestamp)
    into 'YYYY-MM-DD'. Required because rebalance_dates is np.datetime64 and
    str(np.datetime64) yields '2024-01-31T00:00:00.000000000' which breaks string
    comparison against ETF price df['date'] columns formatted as 'YYYY-MM-DD'."""
    if isinstance(d, str):
        return d[:10]  # in case it's an ISO timestamp
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _calc_period_return(weights: dict, etf_prices: dict, start, end) -> float:
    if not weights:
        return 0.0
    s = _normalize_date_str(start)
    e = _normalize_date_str(end)
    total_ret = 0.0
    for etf_code, w in weights.items():
        if etf_code not in etf_prices:
            continue
        df = etf_prices[etf_code]
        df_period = df[(df["date"] >= s) & (df["date"] <= e)]
        if len(df_period) < 2:
            continue
        ret = df_period["close"].iloc[-1] / df_period["close"].iloc[0] - 1
        total_ret += w * ret
    return total_ret
