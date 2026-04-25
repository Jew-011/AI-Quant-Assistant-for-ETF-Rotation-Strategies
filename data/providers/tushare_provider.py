"""
Tushare 数据提供商，用于替代 AKShare 的 fund_etf_spot_em 等易断连接口。
支持自定义 API 地址（如代理）。含重试 + 超时保护。
"""
import os
import time
from typing import Dict, List

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from .base import BaseDataProvider

MAX_RETRIES = 3
RETRY_BASE_WAIT = 3  # 首次重试等待秒数，后续指数退避


def _is_permission_denied_error(exc: Exception) -> bool:
    """Tushare returns several different messages that all mean
    "this account cannot call this endpoint". Treat them uniformly so the
    caller can fall back to AKShare instead of failing the whole pipeline."""
    err_str = str(exc)
    keywords = (
        "没有接口",       # endpoint not subscribed
        "无权限",         # no permission
        "访问权限",       # access permission denied
        "无效的 token",   # invalid token (free / expired)
        "无效的token",
        "token 无效",
        "积分",           # not enough credits
        "权限不足",
    )
    return any(kw in err_str for kw in keywords)


def _to_ts_date(s: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return s.replace("-", "")


def _code_to_ts(code: str) -> str:
    """801120 -> 801120.SI(申万), 512400 -> 512400.SH, 159996 -> 159996.SZ"""
    if code.startswith(("51", "56")):
        return f"{code}.SH"
    if code.startswith(("15", "16")):
        return f"{code}.SZ"
    if code.startswith("80"):
        return f"{code}.SI"
    return f"{code}.SI"


def _retry_call(func, label: str, retries: int = MAX_RETRIES):
    """带指数退避重试的 API 调用包装。"""
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            err_str = str(e)
            is_retryable = any(kw in err_str.lower() for kw in [
                "timed out", "timeout", "connection", "ip数量超限",
                "reset by peer", "broken pipe", "服务器繁忙",
            ])
            if is_retryable and attempt < retries - 1:
                wait = RETRY_BASE_WAIT * (2 ** attempt)
                print(f"[TushareProvider] {label} 第{attempt+1}次失败: {e} → {wait}s 后重试", flush=True)
                time.sleep(wait)
            else:
                raise
    return None  # unreachable


class TushareProvider(BaseDataProvider):
    """Tushare Pro 数据提供商（含重试 + 超时保护）。"""

    def __init__(self):
        import tushare as ts
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            raise ValueError("请设置环境变量 TUSHARE_TOKEN")
        self._pro = ts.pro_api(token)
        api_url = os.getenv("TUSHARE_API_URL", "").strip()
        if api_url:
            self._pro._DataApi__token = token
            self._pro._DataApi__http_url = api_url.rstrip("/")
        self._akshare_fallback = None

    def _get_akshare_fallback(self):
        if self._akshare_fallback is None:
            from .akshare_provider import AKShareProvider

            self._akshare_fallback = AKShareProvider()
        return self._akshare_fallback

    def get_industry_index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Shenwan industry index: must use sw_daily (index_daily does not cover SW).

        Two-layer resilience:
          1. Some Tushare proxies (e.g. xiaodefa.cn) silently rate-limit by returning an empty
             DataFrame instead of raising. We retry up to 2 times with longer pauses.
          2. If still empty (proxy is hard-throttling us), fall back to AKShare's
             ``index_hist_sw`` which uses a completely different upstream (sina / SW website),
             so it is not affected by Tushare proxy issues nor eastmoney outages.
        """
        ts_code = _code_to_ts(code)
        max_empty_retries = 2
        for empty_attempt in range(max_empty_retries + 1):
            try:
                df = _retry_call(
                    lambda: self._pro.sw_daily(
                        ts_code=ts_code,
                        start_date=_to_ts_date(start_date),
                        end_date=_to_ts_date(end_date),
                    ),
                    label=f"sw_daily({ts_code})",
                )
            except Exception as e:
                print(f"[TushareProvider] sw_daily({ts_code}) raised: {e} → falling back to AKShare", flush=True)
                return self._akshare_fallback_industry(code, start_date, end_date, reason="exception")

            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "date", "open": "open", "high": "high",
                    "low": "low", "close": "close", "vol": "volume"
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df[["date", "open", "high", "low", "close", "volume"]]

            if empty_attempt < max_empty_retries:
                wait = 2.0 + empty_attempt * 1.5
                print(
                    f"[TushareProvider] sw_daily({ts_code}) returned empty (likely silent rate-limit) "
                    f"→ retry {empty_attempt + 1}/{max_empty_retries} in {wait:.1f}s",
                    flush=True,
                )
                time.sleep(wait)

        return self._akshare_fallback_industry(code, start_date, end_date, reason="empty after retries")

    def _akshare_fallback_industry(
        self, code: str, start_date: str, end_date: str, reason: str
    ) -> pd.DataFrame:
        """Fall back to AKShare for Shenwan industry daily. Logs the reason so the
        operator can see WHY we fell back (rate-limit vs. exception)."""
        try:
            print(f"[TushareProvider] sw_daily({code}) → AKShare fallback ({reason})", flush=True)
            df = self._get_akshare_fallback().get_industry_index_daily(code, start_date, end_date)
            if df is None or df.empty:
                print(f"[TushareProvider] AKShare fallback for sw({code}) ALSO empty", flush=True)
                return pd.DataFrame()
            print(f"[TushareProvider] AKShare fallback for sw({code}) recovered {len(df)} rows", flush=True)
            return df
        except Exception as e:
            print(f"[TushareProvider] AKShare fallback for sw({code}) raised: {e}", flush=True)
            return pd.DataFrame()

    def get_etf_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        ts_code = _code_to_ts(code)
        max_empty_retries = 2
        for empty_attempt in range(max_empty_retries + 1):
            try:
                df = _retry_call(
                    lambda: self._pro.fund_daily(
                        ts_code=ts_code,
                        start_date=_to_ts_date(start_date),
                        end_date=_to_ts_date(end_date),
                    ),
                    label=f"fund_daily({ts_code})",
                )
            except Exception as e:
                if _is_permission_denied_error(e):
                    print(f"[TushareProvider] fund_daily({ts_code}) no permission, falling back to AKShare", flush=True)
                    return self._get_akshare_fallback().get_etf_daily(code, start_date, end_date)
                print(f"[TushareProvider] fund_daily({ts_code}) final failure: {e}", flush=True)
                return pd.DataFrame()

            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "date", "open": "open", "high": "high",
                    "low": "low", "close": "close", "vol": "volume", "amount": "turnover"
                })
                df["date"] = pd.to_datetime(df["date"])
                df["turnover"] = df["turnover"] * 1000  # qian (thousand yuan) -> yuan
                return df[["date", "open", "high", "low", "close", "volume", "turnover"]]

            if empty_attempt < max_empty_retries:
                wait = 2.0 + empty_attempt * 1.5
                print(
                    f"[TushareProvider] fund_daily({ts_code}) returned empty (likely silent rate-limit) "
                    f"→ retry {empty_attempt + 1}/{max_empty_retries} in {wait:.1f}s",
                    flush=True,
                )
                time.sleep(wait)

        # All retries returned empty — fall back to AKShare. AKShare's get_etf_daily
        # uses eastmoney (which may also be flaky), but it's our last-resort source.
        print(
            f"[TushareProvider] fund_daily({ts_code}) empty after {max_empty_retries} retries "
            f"→ AKShare fallback",
            flush=True,
        )
        try:
            return self._get_akshare_fallback().get_etf_daily(code, start_date, end_date)
        except Exception as e:
            print(f"[TushareProvider] AKShare fallback for ETF {code} failed: {e}", flush=True)
            return pd.DataFrame()

    def get_etf_fund_flow(self, code: str, days: int = 20) -> pd.DataFrame:
        """Estimate ETF net-inflow from daily share-change x close-price.

        Tushare does not expose a direct "money flow" feed for ETFs, but
        ``fund_share`` returns the outstanding share count per trade day.
        The day-over-day change in shares, multiplied by that day's close
        price, is a clean proxy for net subscription / redemption money
        flow:

            net_inflow_t = (share_t - share_{t-1}) x close_t

        Returns a DataFrame with columns [date, net_inflow] (yuan).
        Empty DataFrame when xiaodefa silently rate-limits, when the ETF
        has no share history, or on permission errors.
        """
        from datetime import datetime, timedelta
        ts_code = _code_to_ts(code)
        # Pull a generous window so day-over-day diff has enough rows even
        # when the ETF was not actively traded every day.
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=int(days * 2.5) + 30)
        start, end = start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")

        try:
            shares_df = _retry_call(
                lambda: self._pro.fund_share(
                    ts_code=ts_code, start_date=start, end_date=end
                ),
                label=f"fund_share({ts_code})",
            )
        except Exception as e:
            if _is_permission_denied_error(e):
                print(f"[TushareProvider] fund_share({ts_code}) no permission", flush=True)
            else:
                print(f"[TushareProvider] fund_share({ts_code}) failed: {e}", flush=True)
            return pd.DataFrame()

        if shares_df is None or shares_df.empty:
            return pd.DataFrame()

        # Pull matching close prices to convert share-deltas to yuan.
        try:
            price_df = _retry_call(
                lambda: self._pro.fund_daily(
                    ts_code=ts_code, start_date=start, end_date=end
                ),
                label=f"fund_daily({ts_code})",
            )
        except Exception:
            price_df = None

        shares_df = shares_df.sort_values("trade_date").reset_index(drop=True)
        # fd_share is in 万份 (10k-share units) → yuan needs *1e4
        shares_df["fd_share"] = pd.to_numeric(shares_df["fd_share"], errors="coerce") * 1e4
        shares_df["share_delta"] = shares_df["fd_share"].diff()

        if price_df is not None and not price_df.empty:
            price_df = price_df.sort_values("trade_date")[["trade_date", "close"]]
            merged = shares_df.merge(price_df, on="trade_date", how="left")
            merged["close"] = pd.to_numeric(merged["close"], errors="coerce").ffill().bfill()
        else:
            # No price → assume nominal price 1.0 (so net_inflow == share_delta in shares)
            merged = shares_df.copy()
            merged["close"] = 1.0

        merged["net_inflow"] = (merged["share_delta"] * merged["close"]).fillna(0.0)
        merged["date"] = pd.to_datetime(merged["trade_date"])
        out = merged[["date", "net_inflow"]].dropna().reset_index(drop=True)
        # Drop the very first row (NaN diff) and trim to the requested window.
        return out.tail(days).reset_index(drop=True)

    def get_northbound_flow(self, start_date: str, end_date: str) -> pd.DataFrame:
        # Tushare 有 hsgt 相关接口，此处暂不实现
        return pd.DataFrame()

    def get_etf_info_batch(self, codes: List[str]) -> Dict[str, dict]:
        """从 fund_daily 取最新成交额；规模尝试 etf_share_size，否则置 0。"""
        result = {}
        for code in codes:
            ts_code = _code_to_ts(code)
            size = 0.0
            turnover = 0.0
            name = "N/A"
            try:
                # 最近交易日 fund_daily（取最近一个月内的最新）
                from datetime import datetime, timedelta
                end = datetime.now()
                start = end - timedelta(days=60)
                df = self._pro.fund_daily(
                    ts_code=ts_code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
                if not df.empty:
                    df = df.sort_values("trade_date", ascending=False)
                    latest = df.iloc[0]
                    turnover = float(latest.get("amount", 0) or 0) * 1000  # qian-yuan -> yuan

                # Pull current size from etf_share_size (needs >= 5000 points).
                # Real columns are `total_size` (wan-yuan) and `total_share`
                # (wan-fen). Some ETFs are missing from this dataset, so we
                # fall back to fund_basic.issue_amount below.
                try:
                    sz = self._pro.etf_share_size(ts_code=ts_code)
                    if sz is not None and not sz.empty:
                        sz = sz.sort_values("trade_date", ascending=False)
                        latest_sz = sz.iloc[0]
                        val = latest_sz.get("total_size")
                        if val is None or pd.isna(val) or float(val) == 0:
                            val = latest_sz.get("total_share")
                        if val is not None and not pd.isna(val):
                            size = float(val) * 1e4  # wan-yuan -> yuan
                except Exception:
                    pass

                # Always pull fund name; opportunistically use issue_amount as
                # a size fallback when etf_share_size has no row for this ETF.
                try:
                    fb = self._pro.fund_basic(ts_code=ts_code)
                    if fb is not None and not fb.empty:
                        row = fb.iloc[0]
                        name = str(row.get("name", "N/A"))
                        if size == 0:
                            issue = row.get("issue_amount")
                            if issue is not None and not pd.isna(issue) and float(issue) > 0:
                                size = float(issue) * 1e8  # yi-yuan -> yuan
                except Exception:
                    pass
            except Exception as e:
                if _is_permission_denied_error(e):
                    print(f"[TushareProvider] get_etf_info({code}) fund_daily 无权限，批量回退 AKShare")
                    return self._get_akshare_fallback().get_etf_info_batch(codes)
                print(f"[TushareProvider] get_etf_info({code}) 失败: {e}")
            result[code] = {
                "code": code,
                "name": name,
                "fund_size": size,
                "avg_daily_turnover": turnover,
            }
        return result

    def get_etf_info(self, code: str) -> dict:
        return self.get_etf_info_batch([code])[code]
