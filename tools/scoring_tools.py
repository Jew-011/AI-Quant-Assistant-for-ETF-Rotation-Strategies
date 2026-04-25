import io
import pandas as pd
from langchain_core.tools import tool


def _has_variance(series: pd.Series) -> bool:
    """检查序列是否有区分度（非全部相同）。"""
    return series.nunique() > 1


def _classify_dual_axis(df: pd.DataFrame) -> pd.DataFrame:
    """标准双轴四象限：趋势分 × 共识分，以中位数为界。"""
    trend_med = df["trend_score"].median()
    consensus_med = df["consensus_score"].median()

    def classify(row):
        t, c = row["trend_score"], row["consensus_score"]
        if t > trend_med and c > consensus_med:
            return "黄金配置区"
        if t <= trend_med and c > consensus_med:
            return "左侧观察区"
        if t > trend_med and c <= consensus_med:
            return "高危警示区"
        return "垃圾规避区"

    df["quadrant"] = df.apply(classify, axis=1)
    return df


def _classify_trend_only(df: pd.DataFrame) -> pd.DataFrame:
    """共识数据缺失时，仅按趋势分排序做四档划分。"""
    n = len(df)
    df = df.sort_values("trend_score", ascending=False).reset_index(drop=True)
    q1 = n // 4
    q2 = n // 2
    q3 = q1 + q2

    def classify(idx):
        if idx < q1:
            return "黄金配置区"
        if idx < q2:
            return "左侧观察区"
        if idx < q3:
            return "高危警示区"
        return "垃圾规避区"

    df["quadrant"] = [classify(i) for i in range(n)]
    return df


@tool
def score_quadrant(factor_summary: str) -> str:
    """
    Assign each industry to a quadrant (Golden/LeftSide/Danger/Garbage)
    based on trend and consensus scores.

    Args:
        factor_summary: Factor summary table as text (output from calc_factors)
    """
    df = pd.read_csv(io.StringIO(factor_summary), sep=r"\s{2,}", engine="python")

    if "trend_score" not in df.columns or "consensus_score" not in df.columns:
        return "Error: factor_summary must contain trend_score and consensus_score columns."

    if _has_variance(df["consensus_score"]):
        df = _classify_dual_axis(df)
    else:
        df = _classify_trend_only(df)

    output = df[["industry", "trend_score", "consensus_score", "quadrant"]].sort_values("trend_score", ascending=False)
    return output.to_string(index=False)


def score_quadrant_df(factor_df: pd.DataFrame) -> pd.DataFrame:
    """基于因子 DataFrame 划分四象限，返回带 quadrant 列的 DataFrame。供回测等程序化调用。"""
    if factor_df.empty or "trend_score" not in factor_df.columns or "consensus_score" not in factor_df.columns:
        return pd.DataFrame()
    df = factor_df.copy()

    if _has_variance(df["consensus_score"]):
        df = _classify_dual_axis(df)
    else:
        df = _classify_trend_only(df)

    return df[["industry", "trend_score", "consensus_score", "quadrant"]].sort_values("trend_score", ascending=False)
