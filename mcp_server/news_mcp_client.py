"""
Thin MCP client used by the agent (and frontend) to talk to the news MCP
server. Supports both:

- ``mode='stdio'``: spawns ``python -m mcp_server.news_mcp_server`` as a
  subprocess (no extra setup).
- ``mode='http'``: connects to an already-running HTTP MCP server.

Each call handles the full MCP session handshake, tool invocation, and cleanup.
Result is returned as plain text — same interface as the legacy news tools.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from agent.patterns.pattern_log import log_pattern_use

_ROOT = Path(__file__).resolve().parent.parent


async def _call_via_stdio(
    tool_name: str,
    args: dict[str, Any],
    timeout: float = 30.0,
) -> str:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    # Pass env (so the child can load JINA / ALPHAVANTAGE keys)
    env = {k: v for k, v in os.environ.items() if v is not None}
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "mcp_server.news_mcp_server"],
        env=env,
        cwd=str(_ROOT),
    )
    async with Client(transport) as client:
        result = await asyncio.wait_for(
            client.call_tool(tool_name, args), timeout=timeout
        )
        parts = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        # Structured data fallback
        structured = getattr(result, "structured_content", None)
        if structured:
            return str(structured)
        return str(result)


async def _call_via_http(
    url: str,
    tool_name: str,
    args: dict[str, Any],
    timeout: float = 30.0,
) -> str:
    from fastmcp import Client

    async with Client(url) as client:
        result = await asyncio.wait_for(
            client.call_tool(tool_name, args), timeout=timeout
        )
        parts = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts) or str(result)


def call_mcp_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    mode: str = "stdio",
    url: str = "http://127.0.0.1:8765/mcp",
    thread_id: str = "default",
) -> str:
    """Synchronous entry point used by LangChain tools."""
    args = args or {}
    log_pattern_use(
        thread_id,
        10,
        "MCP",
        "call_mcp_tool",
        f"tool={tool_name} mode={mode}",
    )
    try:
        if mode == "http":
            coro = _call_via_http(url, tool_name, args)
        else:
            coro = _call_via_stdio(tool_name, args)
        return asyncio.run(coro)
    except RuntimeError as exc:
        # Event-loop already running (e.g. Streamlit). Fall back to new thread.
        if "already running" in str(exc).lower():
            import concurrent.futures

            def _runner():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_runner).result()
        return f"MCP error: {exc}"
    except Exception as exc:
        log_pattern_use(thread_id, 10, "MCP", "mcp_error", str(exc))
        return f"MCP error: {exc}"


async def list_mcp_tools_async(mode: str = "stdio", url: str | None = None) -> list[dict]:
    """Return the list of tools exposed by the MCP server (for diagnostics/UI)."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    if mode == "http":
        client_arg = url or "http://127.0.0.1:8765/mcp"
    else:
        env = {k: v for k, v in os.environ.items() if v is not None}
        client_arg = StdioTransport(
            command=sys.executable,
            args=["-m", "mcp_server.news_mcp_server"],
            env=env,
            cwd=str(_ROOT),
        )
    async with Client(client_arg) as client:
        tools = await client.list_tools()
        return [
            {
                "name": t.name,
                "description": (t.description or "")[:260],
                "input_schema": getattr(t, "input_schema", None),
            }
            for t in tools
        ]


def list_mcp_tools(mode: str = "stdio", url: str | None = None) -> list[dict]:
    try:
        return asyncio.run(list_mcp_tools_async(mode=mode, url=url))
    except RuntimeError:
        import concurrent.futures

        def _runner():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(list_mcp_tools_async(mode=mode, url=url))
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_runner).result()
    except Exception as exc:
        return [{"name": "error", "description": str(exc)}]
