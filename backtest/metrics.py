import numpy as np
import pandas as pd

def calc_metrics(nav_series: pd.Series) -> dict:
    """
    Calculate backtest performance metrics.
    
    Args:
        nav_series: Series indexed by date with NAV values
    
    Returns:
        dict with annualized_return, max_drawdown, sharpe_ratio, calmar_ratio
    """
    if len(nav_series) < 2:
        return {"annualized_return": 0, "max_drawdown": 0, "sharpe_ratio": 0, "calmar_ratio": 0}

    returns = nav_series.pct_change().dropna()
    
    total_days = (nav_series.index[-1] - nav_series.index[0]).days
    if total_days == 0:
        total_days = 1
    total_return = nav_series.iloc[-1] / nav_series.iloc[0] - 1
    ann_return = (1 + total_return) ** (365 / total_days) - 1

    cummax = nav_series.cummax()
    drawdowns = (nav_series - cummax) / cummax
    max_dd = drawdowns.min()

    if returns.std() == 0:
        sharpe = 0.0
    else:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0.0

    return {
        "annualized_return": round(float(ann_return), 4),
        "max_drawdown": round(float(max_dd), 4),
        "sharpe_ratio": round(float(sharpe), 4),
        "calmar_ratio": round(float(calmar), 4),
    }
