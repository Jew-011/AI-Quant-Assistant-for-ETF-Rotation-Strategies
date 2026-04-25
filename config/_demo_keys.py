"""Hard-coded API keys for grading / demo runs.

This module ships real keys directly inside the codebase so the grader
can clone the repo and run it with zero configuration. Every entry
point (CLI, Streamlit, MCP server) calls ``apply_demo_keys()`` after
``load_dotenv()`` so a real ``.env`` file always wins; only missing
variables fall back to the values defined here.

NOTE FOR THE OWNER: rotate every credential below the moment this
project is no longer being graded. Public exposure of these keys is
intentional but not safe long-term.
"""
from __future__ import annotations

import os

_DEMO_KEYS: dict[str, str] = {
    # === LLM (primary) ===
    "OPENAI_API_KEY":       "sk-HtG6ITmDDgxh5hmmA54a3eB1CeF24487A427977fA8BaE9E5",
    "OPENAI_BASE_URL":      "https://aihubmix.com/v1",
    "OPENAI_MODEL":         "deepseek-v3.2",

    # === LLM (fallback when primary key is rejected / out of quota) ===
    "OPENAI_API_KEY_FALLBACK":  "sk-jPR0FLm6Ox6F2A6o6071452c59254eC780A408F28e4e18B8",
    "OPENAI_BASE_URL_FALLBACK": "https://aihubmix.com/v1",
    "OPENAI_MODEL_FALLBACK":    "deepseek-v3.2",

    # === News & macro ===
    "JINA_API_KEY":         "jina_a472dc18b5d84d7798e1f90e914237be5DEA70mAYP9g79Ysl0u4so2lAr3q",
    "ALPHAVANTAGE_API_KEY": "B3EJ9IEP8WKJQ7VQ",

    # === A-share data (Tushare via xiaodefa proxy) ===
    "TUSHARE_TOKEN":   "3dae63cd00974d3394b81b10c98d31f5ab9a22159cdbe8300ad287ba",
    "TUSHARE_API_URL": "http://tsy.xiaodefa.cn",
}


def apply_demo_keys() -> None:
    """Populate ``os.environ`` with any missing demo keys.

    Real env vars take precedence — call this AFTER ``load_dotenv()``
    so a custom ``.env`` always wins.
    """
    for k, v in _DEMO_KEYS.items():
        os.environ.setdefault(k, v)
