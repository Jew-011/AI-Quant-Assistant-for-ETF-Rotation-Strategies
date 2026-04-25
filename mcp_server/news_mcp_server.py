"""
Pattern 10: MCP (Model Context Protocol) server for news & macro tools.

This is a **true** MCP server built with FastMCP. It exposes the news-tool
functions over the MCP protocol so that *any* MCP-compatible agent (not just
ours) could plug into it.

Run standalone:
    python -m mcp_server.news_mcp_server            # stdio transport (default)
    python -m mcp_server.news_mcp_server --http     # streamable HTTP transport

The frontend / graph consume it via ``mcp_server.news_mcp_client``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make project root importable when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except Exception:
    pass

from fastmcp import FastMCP

# Re-use the existing plain functions (not the @tool-decorated versions)
from tools.news_tools import (
    _fetch_akshare_flash,
    _fetch_alphavantage,
    _fetch_jina,
    _fetch_macro_akshare,
    _fetch_macro_alphavantage,
    _format_news,
)

mcp = FastMCP(
    name="etf-news-mcp",
    instructions=(
        "Exposes Chinese & global financial news, plus macro events. "
        "Call search_news_cn for A-share / Chinese news, get_macro_events for "
        "macro, and search_global_news for cross-market news."
    ),
)


@mcp.tool
def search_news_cn(keywords: str, limit: int = 20) -> str:
    """
    Search recent Chinese finance news (AKShare 财联社 + Jina fallback).

    Args:
        keywords: Chinese keywords, e.g. '半导体 关税'
        limit: Max number of results (default 20)
    """
    items = _fetch_akshare_flash(keywords, limit=limit)
    jk = os.environ.get("JINA_API_KEY")
    if jk:
        items.extend(_fetch_jina(keywords or "A股 财经 新闻", jk, limit=5))
    if not items:
        return f"未找到与 '{keywords}' 相关的中国财经新闻。"
    return _format_news(items[:limit])


@mcp.tool
def search_global_news(keywords: str = "", limit: int = 15) -> str:
    """
    Search global markets news via Alpha Vantage news-sentiment.

    Args:
        keywords: free-text keywords (optional)
        limit: Max results
    """
    avk = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not avk:
        return "ALPHAVANTAGE_API_KEY 未配置。"
    items = _fetch_alphavantage(
        keywords,
        topics="financial_markets,technology,economy_macro",
        api_key=avk,
        limit=limit,
    )
    if not items:
        return f"未找到与 '{keywords}' 相关的全球新闻。"
    return _format_news(items[:limit])


@mcp.tool
def get_macro_events(days: int = 14) -> str:
    """
    Return recent macro-economic events: 金十 flash + Alpha Vantage economy
    topics (monetary, fiscal, macro).

    Args:
        days: Look-back window in days (default 14)
    """
    items = _fetch_macro_akshare()
    avk = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
    if avk:
        items.extend(_fetch_macro_alphavantage(avk, limit=10))
    if not items:
        return "暂无宏观事件数据。"
    seen, deduped = set(), []
    for x in items:
        t = x.get("title", "") or x.get("content", "")[:80]
        if t and t not in seen:
            seen.add(t)
            deduped.append(x)
    return _format_news(deduped[:20])


@mcp.resource("etf://server-info")
def server_info() -> str:
    """Server self-description resource."""
    return (
        "ETF News MCP Server\n"
        "Tools: search_news_cn, search_global_news, get_macro_events.\n"
        "Data sources: AKShare (财联社 / 金十), Jina Reader, Alpha Vantage."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ETF News MCP Server")
    parser.add_argument(
        "--http", action="store_true", help="Use HTTP transport instead of stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.http:
        print(
            f"[mcp] starting HTTP transport on http://{args.host}:{args.port}",
            file=sys.stderr,
            flush=True,
        )
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        print("[mcp] starting stdio transport", file=sys.stderr, flush=True)
        mcp.run()


if __name__ == "__main__":
    main()
