from langchain_core.tools import tool


_LABELS = {
    "en": {
        "exec_failed": "[BACKTEST] Execution failed: {err}\nPlease verify TUSHARE_TOKEN is set and data is reachable.",
        "header":      "[BACKTEST] {market} | {start} ~ {end} | rebalance: {freq}",
        "metrics":     "Annualized: {ann:.2f}% | Max Drawdown: {mdd:.2f}% | Sharpe: {sharpe:.2f} | Calmar: {calmar:.2f}",
        "footer":      "See nav_series / trades for the equity curve and trade log.",
    },
    "zh": {
        "exec_failed": "[BACKTEST] 回测执行失败: {err}\n请确保 TUSHARE_TOKEN 已设置且数据可获取。",
        "header":      "[BACKTEST] {market} | {start} ~ {end} | 调仓: {freq}",
        "metrics":     "年化收益: {ann:.2f}% | 最大回撤: {mdd:.2f}% | 夏普: {sharpe:.2f} | Calmar: {calmar:.2f}",
        "footer":      "净值曲线与交易记录见 nav_series / trades。",
    },
}


def _L(lang: str) -> dict:
    return _LABELS.get(lang, _LABELS["en"])


@tool
def run_backtest(
    market: str = "a_share",
    start_date: str = "2023-01-01",
    end_date: str = "2025-01-01",
    rebalance_freq: str = "monthly",
    lang: str = "en",
) -> str:
    """
    Run a historical backtest of the ETF rotation strategy.
    On each rebalance date, compute factors + four-quadrant scores → pick the golden allocation
    region → equal-weight allocate → use ETF prices to compute returns.

    Args:
        market: Market identifier (a_share, hk, us)
        start_date: Backtest start date YYYY-MM-DD
        end_date: Backtest end date YYYY-MM-DD
        rebalance_freq: Rebalance frequency ('monthly' or 'weekly')
        lang: Output language for the summary string ('en' or 'zh'). Defaults to 'en'.
    """
    L = _L(lang)
    try:
        from backtest.pipeline import run_backtest_pipeline

        result = run_backtest_pipeline(
            market=market,
            start_date=start_date,
            end_date=end_date,
            rebalance_freq=rebalance_freq,
        )
    except Exception as e:
        return L["exec_failed"].format(err=e)

    if "error" in result:
        return f"[BACKTEST] {result['error']}"

    m = result.get("metrics", {})
    ann_ret = m.get("annualized_return", 0) * 100
    mdd = m.get("max_drawdown", 0) * 100
    sharpe = m.get("sharpe_ratio", 0)
    calmar = m.get("calmar_ratio", 0)

    summary = "\n".join([
        L["header"].format(market=market, start=start_date, end=end_date, freq=rebalance_freq),
        L["metrics"].format(ann=ann_ret, mdd=mdd, sharpe=sharpe, calmar=calmar),
        L["footer"],
    ])
    return summary
