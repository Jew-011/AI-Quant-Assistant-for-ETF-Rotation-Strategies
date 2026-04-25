"""
LangChain tools that go through the MCP protocol (Pattern 10).

Exposing these alongside the direct tools lets the Agent (and the frontend)
demonstrate that the system supports both native and MCP-mediated access.
"""
from __future__ import annotations

import os

from langchain_core.tools import tool

from mcp_server.news_mcp_client import call_mcp_tool

_DEFAULT_MODE = os.getenv("ETF_MCP_MODE", "stdio").lower()
_DEFAULT_URL = os.getenv("ETF_MCP_URL", "http://127.0.0.1:8765/mcp")


@tool
def mcp_search_news_cn(keywords: str, limit: int = 15) -> str:
    """
    [Pattern 10 / MCP] Search A-share financial news via the MCP news server.

    Prefer this over the direct ``search_news_cn`` when you want to demonstrate
    MCP interoperability (e.g., the same server could be reused by other agents).
    """
    return call_mcp_tool(
        "search_news_cn",
        {"keywords": keywords, "limit": limit},
        mode=_DEFAULT_MODE,
        url=_DEFAULT_URL,
    )


@tool
def mcp_get_macro_events(days: int = 14) -> str:
    """
    [Pattern 10 / MCP] Fetch recent macro economic events via the MCP news server.
    """
    return call_mcp_tool(
        "get_macro_events",
        {"days": days},
        mode=_DEFAULT_MODE,
        url=_DEFAULT_URL,
    )


@tool
def mcp_search_global_news(keywords: str = "", limit: int = 15) -> str:
    """
    [Pattern 10 / MCP] Search global markets news via the MCP news server.
    """
    return call_mcp_tool(
        "search_global_news",
        {"keywords": keywords, "limit": limit},
        mode=_DEFAULT_MODE,
        url=_DEFAULT_URL,
    )
