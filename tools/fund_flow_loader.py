"""ETF fund-flow loader with on-disk cache.

Industry → ETF mapping comes from ``config/etf_mapping.yaml``. Net-inflow
series are fetched via ``provider.get_etf_fund_flow`` (Tushare ``fund_share``
proxy by default) and cached as CSV under ``data/cache/fund_flow/`` so we
do not hammer the proxy on every backtest / debate run.

Cache policy:
  - Stored at ``data/cache/fund_flow/<etf_code>.csv``
  - File is reused when its latest ``date`` is from today (intraday) or is
    fresher than ``max_stale_days`` calendar days, otherwise we refresh.
  - Empty result → cache a one-row marker so we don't retry every call.

The single public entry point is ``get_industry_flow_series(name, ...)``
which returns a ``pd.Series[float]`` of yuan-denominated daily net inflow
(positive = subscription, negative = redemption) for the most recent N
days. Returns an empty Series when the industry has no ETF mapping or the
upstream API is down.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
import yaml

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "cache", "fund_flow"
)
os.makedirs(_CACHE_DIR, exist_ok=True)

_MAPPING_CACHE: Optional[Dict[str, dict]] = None


def _load_etf_mapping() -> Dict[str, dict]:
    global _MAPPING_CACHE
    if _MAPPING_CACHE is not None:
        return _MAPPING_CACHE
    path = os.path.join(_CONFIG_DIR, "etf_mapping.yaml")
    if not os.path.isfile(path):
        _MAPPING_CACHE = {}
        return _MAPPING_CACHE
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _MAPPING_CACHE = raw.get("mapping", {}) or {}
    return _MAPPING_CACHE


def get_etf_code_for_industry(industry_name: str) -> Optional[str]:
    """Return the primary ETF code (e.g. "512400") for an industry, or None."""
    mapping = _load_etf_mapping()
    entry = mapping.get(industry_name)
    if not entry:
        return None
    primary = entry.get("primary") or {}
    code = primary.get("code")
    return str(code) if code else None


def _cache_path(code: str) -> str:
    return os.path.join(_CACHE_DIR, f"{code}.csv")


def _is_cache_fresh(path: str, max_stale_days: int = 1) -> bool:
    """Cache is fresh if the latest row's date is today or yesterday."""
    if not os.path.isfile(path):
        return False
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return False
    if df.empty:
        # Empty marker — keep for a few hours then refresh
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        return (datetime.now() - mtime) < timedelta(hours=6)
    latest = df["date"].max()
    if pd.isna(latest):
        return False
    return (datetime.now().date() - latest.date()) <= timedelta(days=max_stale_days)


def _read_cache(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return pd.DataFrame(columns=["date", "net_inflow"])


def _write_cache(path: str, df: pd.DataFrame) -> None:
    try:
        df.to_csv(path, index=False)
    except Exception as e:
        print(f"[fund_flow_loader] cache write failed for {path}: {e}", flush=True)


def get_industry_flow_series(
    industry_name: str,
    provider,
    days: int = 20,
    max_stale_days: int = 1,
) -> pd.Series:
    """Return the daily net-inflow series (yuan) for an industry's primary ETF.

    Empty Series when (a) no ETF mapping exists, (b) the data provider does
    not implement ``get_etf_fund_flow`` (e.g. AKShareProvider), or (c) the
    upstream call fails.
    """
    code = get_etf_code_for_industry(industry_name)
    if not code:
        return pd.Series(dtype=float)

    path = _cache_path(code)
    if _is_cache_fresh(path, max_stale_days=max_stale_days):
        df = _read_cache(path)
    else:
        try:
            df = provider.get_etf_fund_flow(code, days=max(days, 30))
        except Exception as e:
            print(
                f"[fund_flow_loader] {industry_name}({code}) provider failed: {e}",
                flush=True,
            )
            df = pd.DataFrame(columns=["date", "net_inflow"])

        if df is None or df.empty:
            # Write empty-marker so we do not re-hit the proxy in the same run.
            _write_cache(path, pd.DataFrame(columns=["date", "net_inflow"]))
            return pd.Series(dtype=float)

        df = df[["date", "net_inflow"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        _write_cache(path, df)

    if df.empty:
        return pd.Series(dtype=float)
    return df.tail(days)["net_inflow"].astype(float).reset_index(drop=True)
