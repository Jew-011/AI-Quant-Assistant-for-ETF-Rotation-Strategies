"""
Agentic Design Patterns Module.

This package implements the design patterns taught in FTEC5660:
- Pattern 3:  Parallelization          -> patterns.parallel
- Pattern 4:  Reflection               -> patterns.reflection
- Pattern 7:  Multi-Agent Collaboration-> patterns.multi_agent
- Pattern 8:  Memory                   -> patterns.memory
- Pattern 10: MCP                      -> patterns.mcp_client
- Pattern 11: Goal Setting & Monitoring-> patterns.goal_monitor
- Pattern 14: RAG                      -> patterns.rag
- Pattern 15: Inter-agent Comm         -> patterns.multi_agent (message schema)
- Pattern 16: Resource-aware Opt.      -> patterns.resource_tracker
- Pattern 17: Reasoning                -> patterns.reasoning
- Pattern 18: Guardrails               -> patterns.guardrails

Patterns already implemented in legacy code (agent/graph.py, agent/prompts/):
- Pattern 1:  Prompt Chaining          -> prompts/prompt_builder.py
- Pattern 2:  Routing                  -> graph.py router_node + router_schema.py
- Pattern 5:  Tool Use                 -> tools/ + ToolNode
- Pattern 6:  Planning                 -> graph.py planner_node
- Pattern 12: Exception Handling       -> graph.py (router fallback + tool budget)

All patterns are observable via the PATTERN_LOG, which the frontend renders.
"""

from agent.patterns.pattern_log import PATTERN_LOG, log_pattern_use

__all__ = ["PATTERN_LOG", "log_pattern_use"]
