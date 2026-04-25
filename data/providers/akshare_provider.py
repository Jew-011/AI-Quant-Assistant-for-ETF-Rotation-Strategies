import random
import time
import urllib.request as _urlreq
from typing import Callable, Dict, List, TypeVar

import akshare as ak
import pandas as pd
import requests

from .base import BaseDataProvider

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Eastmoney "proxy armor"
# ---------------------------------------------------------------------------
# AKShare's eastmoney calls go through whatever local SOCKS/HTTP proxy the
# user has running (Clash / V2Ray / Mihomo). When that local proxy hiccups it
# silently drops sockets while `requests`' connection pool still thinks they
# are alive — the next call surfaces as ProxyError / RemoteDisconnected and
# the *whole* AKShare retry chain ends up failing.
#
# This module-level monkey-patch makes any eastmoney-bound `requests.get` /
# `requests.post`:
#   1. open a fresh Session (no stale keep-alive)
#   2. explicitly read the Windows system proxy via urllib (so it survives
#      Clash being restarted between calls)
#   3. send `Connection: close` so the proxy never tries to reuse the tunnel
#   4. on ProxyError / ConnectionReset, flush the urllib3 pool and back off
#      4s → 8s → 12s before retrying (vs the original 1–2s, which is too
#      short for a typical local proxy to recover)
#
# Non-eastmoney URLs pass through untouched so this is safe to install
# globally for the whole AKShare provider.
# ---------------------------------------------------------------------------

_PROXY_HICCUP_ERRORS = (
    requests.exceptions.ProxyError,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
    ConnectionResetError,
)


def _flush_connection_pools() -> None:
    """Drop every cached keep-alive socket so the next request goes through
    a brand-new tunnel via the local proxy."""
    try:
        import urllib3

        urllib3.poolmanager.PoolManager().clear()
    except Exception:
        pass


_EASTMONEY_ARMOR_MAX_TRIES = 2  # was 4 — eastmoney 502/RemoteDisconnected is usually a real outage,
                                 # not transient flakiness; fail fast (≈3s lost) instead of slow (≈25s).


def _hardened_eastmoney_call(method: str, url: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("Connection", "close")
    kwargs["headers"] = headers
    kwargs.setdefault("timeout", 8)
    last_exc: BaseException | None = None
    for attempt in range(_EASTMONEY_ARMOR_MAX_TRIES):
        try:
            with requests.Session() as s:
                s.proxies.update(_urlreq.getproxies())
                return s.request(method.upper(), url, **kwargs)
        except _PROXY_HICCUP_ERRORS as exc:
            last_exc = exc
            if attempt == _EASTMONEY_ARMOR_MAX_TRIES - 1:
                break
            wait = 2 + attempt * 1.5 + random.random()  # ~2s, ~3.5s
            print(
                f"[AKShareProvider][armor] eastmoney hiccup ({type(exc).__name__}); "
                f"retry {attempt + 2}/{_EASTMONEY_ARMOR_MAX_TRIES} in {wait:.1f}s"
            )
            _flush_connection_pools()
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def _install_eastmoney_armor() -> None:
    """Idempotently monkey-patch requests.get / requests.post so eastmoney
    URLs go through `_hardened_eastmoney_call`."""
    if getattr(requests, "_eastmoney_armor_installed", False):
        return

    orig_get = requests.get
    orig_post = requests.post

    def _patched_get(url, params=None, **kw):
        if isinstance(url, str) and "eastmoney" in url.lower():
            return _hardened_eastmoney_call("get", url, params=params, **kw)
        return orig_get(url, params=params, **kw)

    def _patched_post(url, data=None, json=None, **kw):
        if isinstance(url, str) and "eastmoney" in url.lower():
            return _hardened_eastmoney_call(
                "post", url, data=data, json=json, **kw
            )
        return orig_post(url, data=data, json=json, **kw)

    requests.get = _patched_get
    requests.post = _patched_post
    requests._eastmoney_armor_installed = True
    print("[AKShareProvider] eastmoney proxy armor installed")


_install_eastmoney_armor()


def _backoff_retry(fn: Callable[[], T], max_tries: int = 5, name: str = "api") -> T:
    """Exponential backoff + jitter, reducing the chance of being
    fingerprinted by the upstream anti-bot layer."""
    for i in range(max_tries):
        try:
            return fn()
        except Exception as e:
            print(f"[AKShareProvider] {name} attempt {i + 1} failed: {e}")
            if i == max_tries - 1:
                raise
            wait = min(30, 2 ** i) + random.random()
            print(f"  -> retrying in {wait:.1f}s (exponential backoff + jitter)...")
            time.sleep(wait)
    raise RuntimeError(f"{name} still failing after {max_tries} retries")

class AKShareProvider(BaseDataProvider):
    """AKShare data provider for A-share market."""

    def _fetch_index_hist(self, code: str, max_retries: int = 3) -> pd.DataFrame:
        """拉取申万行业指数日线（指数退避+抖动重试）。"""
        print(f"[AKShareProvider] 开始拉取行业指数 {code}", flush=True)
        try:
            df = _backoff_retry(
                lambda: ak.index_hist_sw(symbol=code, period="day"),
                max_tries=max_retries,
                name=f"index_hist_sw({code})",
            )
            print(f"[AKShareProvider] 行业指数 {code} 拉取成功，共 {len(df)} 行", flush=True)
            return df
        except Exception:
            print(f"[AKShareProvider] 行业指数 {code} 拉取失败，返回空结果", flush=True)
            return pd.DataFrame()

    def get_industry_index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._fetch_index_hist(code)
        if df.empty:
            return pd.DataFrame()
        try:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            print(f"[AKShareProvider] Failed to process industry index {code}: {e}")
            return pd.DataFrame()

    def get_etf_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "turnover"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            print(f"[AKShareProvider] Failed to get ETF {code}: {e}")
            return pd.DataFrame()

    def get_etf_fund_flow(self, code: str, days: int = 20) -> pd.DataFrame:
        try:
            df = ak.fund_etf_fund_daily_em()
            df = df[df["基金代码"] == code].tail(days)
            df = df.rename(columns={"净值日期": "date", "日增长额": "net_inflow"})
            df["date"] = pd.to_datetime(df["date"])
            return df[["date", "net_inflow"]].reset_index(drop=True)
        except Exception as e:
            print(f"[AKShareProvider] Failed to get ETF fund flow {code}: {e}")
            return pd.DataFrame()

    def get_northbound_flow(self, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
            df = df.rename(columns={"日期": "date", "净流入": "net_inflow"})
            df["date"] = pd.to_datetime(df["date"])
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            print(f"[AKShareProvider] Failed to get northbound flow: {e}")
            return pd.DataFrame()

    def _fetch_etf_spot_df(self, max_retries: int = 5) -> pd.DataFrame:
        """拉取全市场 ETF 行情。东方财富易断连，用指数退避+抖动。"""
        print("[AKShareProvider] 开始拉取全市场 ETF 行情", flush=True)
        try:
            df = _backoff_retry(
                ak.fund_etf_spot_em,
                max_tries=max_retries,
                name="fund_etf_spot_em",
            )
            print(f"[AKShareProvider] 全市场 ETF 行情拉取成功，共 {len(df)} 条", flush=True)
            return df
        except Exception:
            print("[AKShareProvider] 全市场 ETF 行情拉取失败，返回空结果", flush=True)
            return pd.DataFrame()

    def _get_etf_info_yf_fallback(self, code: str) -> dict:
        """yfinance 备用：A 股 ETF 512xxx→.SS，159xxx→.SZ"""
        try:
            import yfinance as yf
            suffix = ".SS" if code.startswith(("51", "56")) else ".SZ"  # 上交所 51/56，深交所 15/16
            ticker = yf.Ticker(code + suffix)
            info = ticker.info
            vol = float(info.get("averageDailyVolume10Day", 0) or 0)
            close = float(info.get("previousClose", 0) or 0)
            turnover = vol * close if vol and close else 0
            return {
                "code": code,
                "name": info.get("shortName", "N/A"),
                "fund_size": float(info.get("totalAssets", 0) or 0),
                "avg_daily_turnover": turnover,
            }
        except Exception as e:
            return {"code": code, "name": "N/A", "fund_size": 0, "avg_daily_turnover": 0}

    def get_etf_info_batch(self, codes: List[str]) -> Dict[str, dict]:
        """一次拉取全市场 ETF；失败时用 yfinance 逐个拉取备用。"""
        print(f"[AKShareProvider] 开始批量获取 ETF 信息，共 {len(codes)} 只", flush=True)
        df = self._fetch_etf_spot_df()
        result = {}
        if df.empty:
            if codes:
                print("[AKShareProvider] fund_etf_spot_em 不可用，改用 yfinance 备用...")
            for i, code in enumerate(codes):
                if i > 0:
                    time.sleep(0.4)  # 限流保护
                print(f"[AKShareProvider] yfinance 备用进度 {i+1}/{len(codes)}: {code}", flush=True)
                result[code] = self._get_etf_info_yf_fallback(code)
            return result
        for i, code in enumerate(codes):
            print(f"[AKShareProvider] ETF 信息进度 {i+1}/{len(codes)}: {code}", flush=True)
            row = df[df["代码"] == code]
            if row.empty:
                result[code] = {"code": code, "name": "N/A", "fund_size": 0, "avg_daily_turnover": 0}
            else:
                r = row.iloc[0]
                result[code] = {
                    "code": code,
                    "name": r.get("名称", "N/A"),
                    "fund_size": float(r.get("最新规模", 0) or 0),
                    "avg_daily_turnover": float(r.get("成交额", 0) or 0),
                }
        print(f"[AKShareProvider] ETF 信息批量获取完成，共返回 {len(result)} 条", flush=True)
        return result

    def get_etf_info(self, code: str) -> dict:
        return self.get_etf_info_batch([code]).get(code, {"code": code, "name": "N/A", "fund_size": 0, "avg_daily_turnover": 0})
