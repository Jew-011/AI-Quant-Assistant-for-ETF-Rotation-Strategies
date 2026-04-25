"""Build market-aware queries for the global news source (Alpha Vantage).

Why this exists
---------------
Alpha Vantage's NEWS_SENTIMENT endpoint:

* indexes English-language news (US, EU, global macro);
* lets us filter by ``topics`` server-side (``financial_markets``,
  ``economy_macro``, ``technology`` ...);
* additionally does a *literal substring match* of ``keywords`` against the
  English title and summary of every article it returns.

The Multi-Agent Debate node used to feed Chinese Shenwan industry names
("电子, 食品饮料") straight into Alpha Vantage. The substring filter
silently dropped every article, so the global-news leg of the 4-way
parallel evidence gather almost always returned empty.

This module translates the A-share Shenwan sector list into English
keywords, picks an appropriate Alpha Vantage ``topics`` bucket per market,
and falls back to safe English defaults for US / HK markets where the
Chinese sector list is not meaningful in the first place.
"""

from __future__ import annotations

import re

# Subset of Shenwan level-1 industries → English keywords that actually
# appear in Alpha Vantage / Reuters / Bloomberg headlines.
SHENWAN_TO_EN: dict[str, str] = {
    "农林牧渔": "agriculture food",
    "基础化工": "chemicals materials",
    "钢铁": "steel iron",
    "有色金属": "metals copper aluminum",
    "电子": "semiconductors electronics technology",
    "家用电器": "appliance consumer electronics",
    "食品饮料": "food beverage staples",
    "纺织服饰": "textile apparel",
    "轻工制造": "light manufacturing",
    "医药生物": "pharmaceutical biotech healthcare",
    "公用事业": "utilities power",
    "交通运输": "transportation logistics",
    "房地产": "real estate property",
    "商业贸易": "retail wholesale",
    "休闲服务": "leisure travel",
    "综合": "diversified",
    "建筑材料": "construction materials cement",
    "建筑装饰": "construction engineering",
    "电气设备": "electrical equipment power",
    "机械设备": "machinery industrial",
    "国防军工": "defense aerospace",
    "汽车": "auto automotive ev",
    "采掘": "mining coal oil",
    "化工": "chemicals",
    "煤炭": "coal energy",
    "石油石化": "oil gas energy",
    "环保": "environmental green",
    "美容护理": "cosmetics personal care",
    "社会服务": "consumer services",
    "传媒": "media entertainment",
    "通信": "telecom communications",
    "计算机": "software cloud ai",
    "非银金融": "insurance broker asset management",
    "银行": "bank financials",
    "电力设备": "power equipment renewable",
    "新能源": "renewable energy solar wind",
}

ALPHAVANTAGE_TOPICS_BY_MARKET: dict[str, str] = {
    "a_share": "economy_macro,economy_fiscal,economy_monetary,financial_markets",
    "us": "financial_markets,economy_macro,technology,earnings",
    "hk": "financial_markets,economy_macro,technology",
}

DEFAULT_GLOBAL_KW_BY_MARKET: dict[str, str] = {
    "a_share": "china equity macro tariff",
    "us": "us equity sector etf earnings",
    "hk": "hong kong hsi china equity",
}


def _split_zh_sector_kw(sector_kw_zh: str) -> list[str]:
    """Split a comma/whitespace separated Chinese sector keyword string."""
    if not sector_kw_zh:
        return []
    parts = re.split(r"[,，、\s/;|]+", sector_kw_zh)
    return [p.strip() for p in parts if p.strip()]


def global_news_query(market: str, sector_kw_zh: str) -> tuple[str, str]:
    """Return ``(keywords_english, topics)`` suitable for Alpha Vantage.

    * ``keywords_english`` is a space-separated string of English terms.
      Alpha Vantage will substring-match it against the article title /
      summary. Keep the list short to avoid over-filtering.
    * ``topics`` is the comma-separated Alpha Vantage topic bucket.
    """
    market = (market or "").lower()
    topics = ALPHAVANTAGE_TOPICS_BY_MARKET.get(
        market, "financial_markets,economy_macro"
    )

    if market == "a_share":
        zh_terms = _split_zh_sector_kw(sector_kw_zh)
        en_words: list[str] = []
        for term in zh_terms:
            mapped = SHENWAN_TO_EN.get(term)
            if mapped:
                en_words.extend(mapped.split())
        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped = [w for w in en_words if not (w in seen or seen.add(w))]
        if not deduped:
            return DEFAULT_GLOBAL_KW_BY_MARKET["a_share"], topics
        # Cap at 6 keywords so Alpha Vantage's substring AND-style filter
        # does not over-restrict the result set.
        return " ".join(deduped[:6]), topics

    if market in ("us", "hk"):
        return DEFAULT_GLOBAL_KW_BY_MARKET[market], topics

    return sector_kw_zh or "global macro", topics


def supports_chinese_sector_news(market: str) -> bool:
    """Whether `search_news_cn` (AKShare / Jina Chinese) is meaningful here.

    For A-share the answer is yes. For US / HK we still surface CN macro
    flashes (china tariff news influences HK and US-listed China names),
    but a Chinese-keyword *sector* search returns junk for US/HK tickers.
    """
    return (market or "").lower() == "a_share"
