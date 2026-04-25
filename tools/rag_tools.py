"""
LangChain-compatible tool that wraps the RAG retrieval function.
Exposed to the agent as ``search_research_library``.
"""
from __future__ import annotations

from langchain_core.tools import tool

from agent.patterns.rag import search_research_library as _search


@tool
def search_research_library(query: str, k: int = 4) -> str:
    """
    Retrieve the top-k most relevant paragraphs from the internal research
    library (thinking framework, architecture doc, business model).

    Use this tool when the user asks about:
    - the meaning / definition of a factor (e.g. "什么是 smart_money")
    - the investment philosophy / four-quadrant rule
    - business model / value proposition rationale
    - architectural design of this agent system

    Args:
        query: plain-text question.
        k: number of paragraphs to return (default 4).
    """
    chunks = _search(query=query, k=k, thread_id="tool")
    if not chunks:
        return "研究库中未找到与查询相关的内容。"
    lines = [f"检索到 {len(chunks)} 条相关片段："]
    for i, ch in enumerate(chunks, 1):
        lines.append(
            f"\n[{i}] {ch.source} (score={ch.score})\n"
            + ch.content[:800]
            + ("\n..." if len(ch.content) > 800 else "")
        )
    return "\n".join(lines)
