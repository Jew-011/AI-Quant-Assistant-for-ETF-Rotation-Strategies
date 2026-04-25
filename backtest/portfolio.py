import pandas as pd
from typing import Dict

def allocate_weights(golden_industries: pd.DataFrame, method: str = "equal") -> Dict[str, float]:
    """
    Allocate portfolio weights to selected industries/ETFs.
    
    Args:
        golden_industries: DataFrame of industries in golden quadrant
        method: 'equal' for equal weight, 'score' for score-weighted
    
    Returns:
        dict mapping ETF code -> weight
    """
    n = len(golden_industries)
    if n == 0:
        return {}

    if method == "equal":
        w = round(0.9 / n, 4)  # 90% allocated, 10% cash reserve
        return {row["industry"]: w for _, row in golden_industries.iterrows()}

    elif method == "score":
        total = golden_industries["trend_score"].sum() + golden_industries["consensus_score"].sum()
        if total == 0:
            return allocate_weights(golden_industries, method="equal")
        weights = {}
        for _, row in golden_industries.iterrows():
            raw_w = (row["trend_score"] + row["consensus_score"]) / total
            weights[row["industry"]] = round(raw_w * 0.9, 4)
        return weights

    return {}
