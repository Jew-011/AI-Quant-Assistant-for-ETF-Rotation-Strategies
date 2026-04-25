from abc import ABC, abstractmethod
import pandas as pd
from typing import List, Optional

class BaseDataProvider(ABC):
    """Data provider abstract base class."""

    @abstractmethod
    def get_industry_index_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Get industry index daily data. Returns DataFrame with columns: date, open, high, low, close, volume."""
        ...

    @abstractmethod
    def get_etf_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Get ETF daily data. Returns DataFrame with columns: date, open, high, low, close, volume, turnover."""
        ...

    @abstractmethod
    def get_etf_fund_flow(self, code: str, days: int = 20) -> pd.DataFrame:
        """Get ETF fund flow data. Returns DataFrame with columns: date, net_inflow."""
        ...

    @abstractmethod
    def get_northbound_flow(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Get northbound/smart money flow by industry. Returns DataFrame with columns: date, industry, net_inflow."""
        ...

    @abstractmethod
    def get_etf_info(self, code: str) -> dict:
        """Get ETF info (fund size, daily turnover). Returns dict with keys: code, name, fund_size, avg_daily_turnover."""
        ...
