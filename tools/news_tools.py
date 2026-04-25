"""
News & Macro tools: AKShare (A-share, free) + Jina (Chinese search) + Alpha Vantage (global, macro)
"""
import os
from datetime import datetime, timedelta

from langchain_core.tools import tool

try:
    import akshare as ak
except ImportError:
    ak = None

try:
    import requests
except ImportError:
    requests = None


def _fetch_akshare_flash(keywords: str = "", limit: int = 20) -> list:
    """Fetch A-share flash / keyword news via AKShare.

    AKShare 1.18 removed `stock_zh_a_alerts_cls`. We fall back to
    Eastmoney's keyword search (`stock_news_em`) which is real-time and
    returns the publish timestamp + article body. When no keyword is
    given we just dump the latest macro-tagged news.
    """
    if ak is None:
        return []
    results: list = []

    # Eastmoney keyword search supports one keyword at a time. We try each
    # space-separated keyword and merge.
    kw_list = [k.strip() for k in (keywords or "宏观").split() if k.strip()] or ["宏观"]
    seen_titles = set()
    for kw in kw_list[:4]:
        try:
            df = ak.stock_news_em(symbol=kw)
        except AttributeError:
            print("[news_tools] WARN ak.stock_news_em not available")
            break
        except Exception as e:
            print(f"[news_tools] WARN ak.stock_news_em('{kw}') failed: {type(e).__name__}: {str(e)[:120]}")
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            title = str(row.get("新闻标题", "")).strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            content = str(row.get("新闻内容", "") or title)
            time_val = str(row.get("发布时间", "")).strip()
            src = str(row.get("文章来源", "Eastmoney")).strip()
            results.append({
                "title":   title[:120],
                "content": content[:500],
                "time":    time_val or "unknown",
                "source":  src or "Eastmoney",
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return results


def _fetch_akshare_js_news(limit: int = 15) -> list:
    """Fetch real-time CN macro / finance news via AKShare.

    AKShare keeps renaming / removing news endpoints between versions
    (`js_news` was removed in 1.18.x). We probe multiple known-good
    endpoints in priority order and STOP at the first one that returns
    non-empty data. Every probe failure is logged loudly so the next
    upstream breakage cannot fail silently again.
    """
    if ak is None:
        print("[news_tools] AKShare not installed -- macro feed unavailable")
        return []

    # Priority order:
    #   1. Cailianshe global telegraph -- real-time (timestamped to the
    #      minute), full body, ~20 fresh items per call.  This is the BEST
    #      signal we have for "what just happened in the macro world".
    #   2. Caixin main news -- editorial daily list (~100 items, dated by URL).
    #   3. Baidu economic calendar / CCTV news -- backstops if both above fail.
    probes = [
        ("stock_info_global_cls", lambda: ak.stock_info_global_cls(),                        "财联社电报"),
        ("stock_news_main_cx",    lambda: ak.stock_news_main_cx(),                           "财新"),
        ("news_economic_baidu",   lambda: ak.news_economic_baidu(date=datetime.now().strftime("%Y%m%d")), "百度宏观日历"),
        ("news_cctv",             lambda: ak.news_cctv(date=datetime.now().strftime("%Y%m%d")),          "央视新闻联播"),
    ]

    for name, fn, source in probes:
        try:
            df = fn()
        except AttributeError:
            print(f"[news_tools] WARN ak.{name} not available in this AKShare version (skipping)")
            continue
        except Exception as e:
            print(f"[news_tools] WARN ak.{name} failed: {type(e).__name__}: {str(e)[:160]}")
            continue
        if df is None or getattr(df, "empty", True):
            continue

        results: list = []
        for _, row in df.iterrows():
            # Title preference: explicit title column first, fallback to body.
            title = ""
            for col in ("标题", "title", "新闻标题", "tag"):
                if col in df.columns and row.get(col):
                    title = str(row.get(col)).strip()
                    break
            body = ""
            for col in ("内容", "content", "summary", "新闻内容"):
                if col in df.columns and row.get(col):
                    body = str(row.get(col)).strip()
                    break
            if not title and not body:
                continue
            if not title:
                title = body[:80]

            # Time: combine 发布日期 + 发布时间 when both exist (Cailianshe).
            dt = ""
            if "发布日期" in df.columns and "发布时间" in df.columns:
                dt = f"{row.get('发布日期','')} {row.get('发布时间','')}".strip()
            else:
                for col in ("datetime", "date", "时间", "发布时间"):
                    if col in df.columns and row.get(col):
                        dt = str(row.get(col))
                        break

            results.append({
                "title":   title[:120],
                "content": (body or title)[:500],
                "time":    dt or "unknown",
                "source":  source,
            })
            if len(results) >= limit:
                break
        if results:
            print(f"[news_tools] ak.{name} -> {len(results)} items ({source})")
            return results

    print("[news_tools] WARN every CN macro probe returned empty")
    return []


def _fetch_jina(keywords: str, api_key: str, limit: int = 3) -> list:
    """Search and scrape via Jina (Chinese-friendly)."""
    if not api_key or not requests:
        return []
    results = []
    try:
        search_url = f"https://s.jina.ai/?q={keywords}&n=5"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "X-Respond-With": "no-content"}
        r = requests.get(search_url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        urls = []
        for item in data.get("data", []):
            if item.get("url"):
                urls.append(item["url"])
        urls = urls[:limit] if limit else urls[:3]
        for url in urls:
            try:
                reader_url = f"https://r.jina.ai/{url}"
                headers_reader = {"Accept": "application/json", "Authorization": api_key, "X-Timeout": "10"}
                rr = requests.get(reader_url, headers=headers_reader, timeout=12)
                if rr.status_code != 200:
                    continue
                j = rr.json()
                d = j.get("data", {})
                results.append({
                    "title": d.get("title", "")[:100],
                    "content": (d.get("content") or d.get("description", ""))[:800],
                    "time": d.get("publishedTime", "unknown"),
                    "source": "Jina",
                    "url": d.get("url", url),
                })
            except Exception:
                continue
    except Exception:
        pass
    return results


def _fetch_alphavantage(keywords: str = "", topics: str = "", api_key: str = "", limit: int = 15) -> list:
    """Fetch global news from Alpha Vantage NEWS_SENTIMENT."""
    if not api_key or not requests:
        return []
    results = []
    key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        return []
    try:
        params = {"function": "NEWS_SENTIMENT", "apikey": key, "sort": "LATEST", "limit": limit}
        if topics:
            params["topics"] = topics
        time_to = datetime.now()
        time_from = time_to - timedelta(days=7)
        params["time_from"] = time_from.strftime("%Y%m%dT%H%M")
        params["time_to"] = time_to.strftime("%Y%m%dT%H%M")
        r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        if "Error Message" in j or "Note" in j:
            return []
        feed = j.get("feed", [])
        for a in feed[:limit]:
            title = a.get("title", "")
            summary = a.get("summary", "")[:600]
            if keywords:
                kws = [k.strip() for k in keywords.split() if k.strip()]
                if kws and not any(kw in title or kw in summary for kw in kws):
                    continue
            results.append({
                "title": title,
                "content": summary,
                "time": a.get("time_published", "unknown"),
                "source": "Alpha Vantage",
                "url": a.get("url", ""),
            })
    except Exception:
        pass
    return results


def _format_news(items: list) -> str:
    if not items:
        return ""
    lines = []
    for i, x in enumerate(items, 1):
        lines.append(f"[{i}] {x.get('title', 'N/A')}")
        lines.append(f"    body: {x.get('content', '')[:400]}...")
        lines.append(f"    time: {x.get('time', 'N/A')} | source: {x.get('source', 'N/A')}")
        lines.append("")
    return "\n".join(lines).strip()


@tool
def search_news(keywords: str, days: int = 7, source: str = "all") -> str:
    """
    Search recent news by keywords. Supports multiple sources:
    - AKShare: A-share flash (财联社) + finance news (金十), free
    - Jina: Web search + scrape, Chinese-friendly (needs JINA_API_KEY)
    - Alpha Vantage: Global news (needs ALPHAVANTAGE_API_KEY)
    
    Args:
        keywords: Search keywords, e.g. '半导体 关税', '有色金属'
        days: Number of recent days to consider
        source: 'all' (default), 'akshare', 'jina', 'alphavantage'
    """
    all_items = []
    if source in ("all", "akshare"):
        items = _fetch_akshare_flash(keywords, limit=15)
        all_items.extend(items)
        if not keywords:
            items2 = _fetch_akshare_js_news(limit=10)
            all_items.extend(items2)
    if source in ("all", "jina"):
        jk = os.environ.get("JINA_API_KEY")
        if jk:
            items = _fetch_jina(keywords or "A股 财经", jk, limit=3)
            all_items.extend(items)
    if source in ("all", "alphavantage"):
        avk = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
        if avk:
            topics = "financial_markets,technology,economy_macro"
            items = _fetch_alphavantage(keywords, topics, avk, limit=10)
            all_items.extend(items)
    if not all_items:
        hint = []
        if source in ("all", "akshare") and ak:
            hint.append("AKShare returned empty (network or upstream API change).")
        if source in ("all", "jina") and not os.environ.get("JINA_API_KEY"):
            hint.append("JINA_API_KEY not configured.")
        if source in ("all", "alphavantage") and not (os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")):
            hint.append("ALPHAVANTAGE_API_KEY not configured.")
        return f"No news matched '{keywords}'." + (" " + " ".join(hint) if hint else "")
    seen = set()
    deduped = []
    for x in all_items:
        t = (x.get("title", ""), x.get("content", "")[:100])
        if t not in seen:
            seen.add(t)
            deduped.append(x)
    return _format_news(deduped[:25])


@tool
def search_news_cn(keywords: str, limit: int = 20) -> str:
    """
    Search A-share / Chinese finance news. Uses AKShare (free) first, then Jina if configured.
    Best for: 半导体 关税, 有色金属 供需, 电力设备 产能
    
    Args:
        keywords: Chinese keywords
        limit: Max results
    """
    items = _fetch_akshare_flash(keywords, limit=limit)
    jk = os.environ.get("JINA_API_KEY")
    if jk:
        items.extend(_fetch_jina(keywords or "A股 财经 新闻", jk, limit=5))
    if not items:
        return f"No Chinese-finance news matched '{keywords}'."
    return _format_news(items[:limit])


def _fetch_macro_alphavantage(api_key: str, limit: int = 15) -> list:
    """Macro news from Alpha Vantage (economy topics)."""
    if not api_key or not requests:
        return []
    try:
        key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
        if not key:
            return []
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": key,
            "topics": "economy_macro,economy_monetary,economy_fiscal",
            "sort": "LATEST",
            "limit": limit,
        }
        time_to = datetime.now()
        time_from = time_to - timedelta(days=14)
        params["time_from"] = time_from.strftime("%Y%m%dT%H%M")
        params["time_to"] = time_to.strftime("%Y%m%dT%H%M")
        r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        if "Error Message" in j or "Note" in j:
            return []
        feed = j.get("feed", [])
        return [{"title": a.get("title", ""), "content": (a.get("summary", ""))[:500], "time": a.get("time_published", "")} for a in feed]
    except Exception:
        return []


def _fetch_macro_akshare() -> list:
    """Macro / economic flash from CN sources (Caixin / Baidu / CCTV) via AKShare."""
    return _fetch_akshare_js_news(limit=15)


# Heuristic relevance filter for AlphaVantage. Their `economy_macro` topic
# leaks lots of US consumer noise (fast-food wages, coffee prices...) that
# is useless for A-share rotation. We only keep articles whose title hints at
# real macro content so the Macro agent isn't drowned in trivia.
_MACRO_RELEVANT = (
    "fed", "federal reserve", "rate", "rates", "inflation", "cpi", "ppi",
    "gdp", "yield", "treasury", "bond", "central bank", "ecb", "boj", "pboc",
    "china", "chinese", "yuan", "renminbi", "tariff", "trade", "geopolitic",
    "stimulus", "fiscal", "deficit", "policy", "recession", "growth",
    "manufacturing", "pmi", "unemployment", "payroll",
)


def _is_macro_relevant(title: str) -> bool:
    if not title:
        return False
    low = title.lower()
    return any(kw in low for kw in _MACRO_RELEVANT)


@tool
def get_macro_events(days: int = 14) -> str:
    """
    Get recent macro economic events / news. Uses:
    - AKShare (Caixin / Baidu economic calendar / CCTV news, free)
    - Alpha Vantage economy topics, filtered for relevance
      (when ALPHAVANTAGE_API_KEY configured)

    Args:
        days: Number of days to look back (Alpha Vantage window only)
    """
    items = _fetch_macro_akshare()
    cn_count = len(items)

    avk = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if avk:
        global_items = _fetch_macro_alphavantage(avk, limit=15)
        # Drop the consumer-noise articles that have nothing to do with macro
        relevant = [x for x in global_items if _is_macro_relevant(x.get("title", ""))]
        if global_items and not relevant:
            print(f"[news_tools] AlphaVantage returned {len(global_items)} items, "
                  f"none passed the macro-relevance filter")
        items.extend(relevant)

    print(f"[news_tools] get_macro_events: cn={cn_count} + global_relevant={len(items)-cn_count}")

    if not items:
        return (
            "No macro event data available. "
            "All upstream macro feeds returned empty just now."
        )
    seen = set()
    deduped = []
    for x in items:
        t = x.get("title", "") or x.get("content", "")[:80]
        if t and t not in seen:
            seen.add(t)
            deduped.append(x)
    return _format_news(deduped[:20])
