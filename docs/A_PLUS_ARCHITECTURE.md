# A+ Upgrade Architecture

This document describes the end-to-end execution graph after the A+ upgrade.
It supplements the original `AGENT_ARCHITECTURE.md`.

## Top-level flow

```
            ┌─────────────────────────────────────┐
  user ──▶  │  input_guardrail  (Pattern 18)      │ ─ blocked? ──▶ finalize (refusal)
            └──────────────┬──────────────────────┘
                           │ ok
                           ▼
            ┌─────────────────────────────────────┐
            │  memory_prep  (Pattern 8)           │   load long-term memory snippet
            └──────────────┬──────────────────────┘
                           ▼
            ┌─────────────────────────────────────┐
            │  router  (Pattern 2)                │   RouterDecision + init GoalState (P11)
            │                                      │   + record_query (P8)
            └──────────────┬──────────────────────┘
                           ▼
            ┌─────────────────────────────────────┐
            │  planner  (Pattern 6)               │   Plan-then-execute
            └──────────────┬──────────────────────┘
                           ▼
             task_key ═══ condition ═══════════════════════════════════════
             ║                                                             ║
             ▼   subgraph                        generic ▼                 ║
  ┌─────────────────────────────────────────┐  ┌─────────────────────┐    ║
  │  weekly_prepare  → weekly_persist       │  │ executor (ReAct)    │    ║
  │  trace_history   → trace_review         │  │   ↕ tools (P5)      │    ║
  │  backtest_compare   (Pattern 3 parallel)│  │                     │    ║
  │  conflict_check     (Pattern 3 parallel)│  └──────────┬──────────┘    ║
  │  rm_portfolio_prepare → rm_…_persist    │             ▼               ║
  │  compliance_risk                        │        goal_update (P11)    ║
  │  multi_agent_debate  (P7 + P3 + P17)    │             ▼               ║
  └──────────────────┬──────────────────────┘        finalize (P6)        ║
                     ▼                                                     ║
                 goal_update (P11)                                         ║
                     ▼                                                     ║
                 finalize (P6)  ◀──────────────────────────────────────────╝
                     ▼
            ┌─────────────────────────────────────┐
            │  reflect  (Pattern 4)               │   Critic → Revise loop
            └──────────────┬──────────────────────┘
                           ▼
            ┌─────────────────────────────────────┐
            │  output_guardrail  (Pattern 18)     │   compliance filter + HITL
            └──────────────┬──────────────────────┘
                           ▼
                         END
```

## Multi-Agent Debate subgraph (Pattern 7 + 3 + 15 + 17)

```
 multi_agent_debate_node
   ├─ Step 1  calc_factors_df
   ├─ Step 2  score_quadrant_df + overlay
   ├─ Step 3  parallel ThreadPool:
   │       ├─ get_macro_events
   │       └─ search_news_cn (top golden sectors)
   ├─ Step 4  run_debate_parallel (Pattern 3 fan-out):
   │       ├─ Quant Agent      (system prompt QUANT_SYSTEM, structured_output=AgentReport)
   │       ├─ Macro Agent      (system prompt MACRO_SYSTEM)
   │       └─ Risk  Agent      (system prompt RISK_SYSTEM)
   └─ Step 5  Coordinator (_aggregate):
           ├─ veto rule        (any veto → exclude, log disagreement)
           ├─ confidence vote  (weighted majority)
           └─ self_consistency_vote (Pattern 17) when margin thin
   Output: DebateVerdict {final_stance_per_sector, disagreements, recommended_sectors, ...}
```

## Cross-cutting observability

- `agent/patterns/pattern_log.py` — per-thread append-only log of every pattern
  event.  The frontend renders it as badges (Chat page) and a histogram (Pattern Dashboard page).
- `agent/patterns/resource_tracker.py` — per-thread token/cost/tool/latency
  record, wired via `CostCallbackHandler` on every `ChatOpenAI` call.

## Side-effects and persistence

| Kind | Path | Used by |
|---|---|---|
| Decision trace (signed artefact) | `traces/<YYYY-MM-DD>/trace_*.json` | weekly_persist / rm_portfolio_persist |
| HITL approval queue              | `traces/hitl/<id>.json`            | output_guardrail, 06 HITL page |
| Long-term user memory            | `traces/memory/<thread_id>.json`   | Pattern 8 |
| RAG vector store                 | `docs/rag_index/index.faiss`       | Pattern 14 |
| MCP server config                | `.env` (reuses news keys)          | Pattern 10 |
