import os
import random
import time
import yaml
import pandas as pd
from langchain_core.tools import tool
from data.providers.akshare_provider import AKShareProvider
from data.providers.yfinance_provider import YFinanceProvider

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def _load_market_config(market: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"market_{market}.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _print_progress(prefix: str, current: int, total: int, name: str, code: str, provider_name: str):
    print(f"[{prefix}] {provider_name} 进度 {current}/{total}: {name}({code})", flush=True)


def _get_provider(market_config: dict):
    provider_name = market_config.get("data_provider", "akshare")
    if provider_name == "tushare":
        try:
            from data.providers.tushare_provider import TushareProvider
            return TushareProvider()
        except Exception as e:
            print(f"[data_tools] Tushare 不可用，回退 AKShare: {e}")
            return AKShareProvider()
    if provider_name == "akshare":
        return AKShareProvider()
    if provider_name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"Unknown data provider: {provider_name}")

@tool
def get_market_data(market: str = "a_share", start_date: str = "2024-01-01", end_date: str = "2025-03-01") -> str:
    """
    Get daily price data for all industries in the specified market.
    Returns a summary of data fetched for each industry.

    Args:
        market: Market identifier (a_share, hk, us)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    config = _load_market_config(market)
    provider = _get_provider(config)
    industries = config.get("industries", [])
    provider_name = config.get("data_provider", "akshare")

    print(
        f"[get_market_data] 开始抓取 {market} 市场数据，共 {len(industries)} 个行业，数据源={provider_name}",
        flush=True,
    )

    results = []
    for i, ind in enumerate(industries):
        _print_progress("get_market_data", i + 1, len(industries), ind["name"], ind["code"], provider_name)
        if i > 0 and provider_name == "akshare":
            time.sleep(0.8 + random.random() * 0.7)  # AKShare 限流保护
        df = provider.get_industry_index_daily(ind["code"], start_date, end_date)
        rows = len(df)
        last_close = df["close"].iloc[-1] if rows > 0 else "N/A"
        results.append(f"{ind['name']}({ind['code']}): {rows} rows, latest close={last_close}")
        if rows == 0:
            print(f"[get_market_data] {ind['name']}({ind['code']}) 未获取到有效数据", flush=True)

    print(f"[get_market_data] 抓取完成，返回 {len(results)} 个行业摘要", flush=True)
    return "\n".join(results) if results else "No data fetched."

@tool
def get_etf_flow_detail(etf_code: str, days: int = 20) -> str:
    """
    Get detailed daily fund flow for a specific ETF.

    Args:
        etf_code: ETF code (e.g. '512400')
        days: Number of recent days to fetch
    """
    provider = AKShareProvider()
    df = provider.get_etf_fund_flow(etf_code, days)
    if df.empty:
        return f"No fund flow data for ETF {etf_code}."
    return df.to_string(index=False)
