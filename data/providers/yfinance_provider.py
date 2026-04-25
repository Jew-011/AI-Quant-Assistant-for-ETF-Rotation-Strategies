import yfinance as yf
import pandas as pd
from .base import BaseDataProvider

class YFinanceProvider(BaseDataProvider):
    """yfinance data provider for HK/US markets. (Placeholder — to be implemented)"""

    def get_industry_index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("YFinanceProvider.get_industry_index_daily not yet implemented")

    def get_etf_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            ticker = yf.Ticker(code)
            df = ticker.history(start=start_date, end=end_date)
            df = df.reset_index()
            df = df.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
            df["turnover"] = df["close"] * df["volume"]
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            return df[["date", "open", "high", "low", "close", "volume", "turnover"]].reset_index(drop=True)
        except Exception as e:
            print(f"[YFinanceProvider] Failed to get ETF {code}: {e}")
            return pd.DataFrame()

    def get_etf_fund_flow(self, code: str, days: int = 20) -> pd.DataFrame:
        raise NotImplementedError("YFinanceProvider.get_etf_fund_flow not yet implemented")

    def get_northbound_flow(self, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("YFinanceProvider.get_northbound_flow not yet implemented")

    def get_etf_info(self, code: str) -> dict:
        try:
            ticker = yf.Ticker(code)
            info = ticker.info
            return {
                "code": code,
                "name": info.get("shortName", "N/A"),
                "fund_size": info.get("totalAssets", 0) or 0,
                "avg_daily_turnover": info.get("averageDailyVolume10Day", 0) * info.get("previousClose", 0),
            }
        except Exception as e:
            print(f"[YFinanceProvider] Failed to get ETF info {code}: {e}")
            return {"code": code, "name": "N/A", "fund_size": 0, "avg_daily_turnover": 0}
