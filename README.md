# AI Quant Assistant for ETF Rotation Strategies

> **FTEC5660 Group Project — The Chinese University of Hong Kong**
> Submitted as the team deliverable for *FinTech Project Workshop*.

A LangGraph-powered agentic system for ETF sector-rotation research. It
takes a researcher, relationship manager or compliance officer through
the full loop — market scan → factor computation → four-quadrant
selection → ETF mapping → multi-agent debate → human-in-the-loop
approval → audit trace — and ships with a 9-page Streamlit frontend that
is fully bilingual (English / 简体中文).

---

## Highlights

- **Heterogeneous multi-agent debate.** Quant, Macro and Risk
  specialists run in parallel — each can be assigned a different LLM —
  and a Coordinator fuses the votes. Every result is cached in both
  English and Chinese so toggling the UI language never re-runs the LLM.
- **Real fund-flow factors.** `etf_flow_contrarian`, `smart_money` and
  `volatility_convergence` are computed from Tushare `fund_share`
  (daily-share-change × close-price ⇒ yuan-denominated net subscription /
  redemption), with a CSV cache that keeps repeated runs cheap.
- **18 of 18 syllabus patterns mapped.** Routing, Planning, ReAct
  Executor, Reflection, Multi-Agent, RAG, MCP, Long-term Memory,
  Self-Consistency Reasoning, Goal Monitoring, Resource Tracking and
  bilingual Guardrails are wired into a single LangGraph state machine.
- **Resilient data layer.** Tushare via the `xiaodefa` proxy, with
  empty-result retries and an automatic AKShare fallback that itself
  routes through proxy-armoured eastmoney sessions.
- **Two-tier LLM fallback.** When the primary OpenAI-compatible endpoint
  is rate-limited or out of quota, the agent transparently retries
  through a configurable secondary key once before failing.
- **Auditability built in.** Every run writes a `trace_*.json` snapshot
  with the full router decision, tool calls, sub-agent reports, HITL
  status and resource usage; reports export to HTML / DOCX / PDF.

---

## What you can do with it

| Role | Task | Outcome |
|---|---|---|
| Researcher | Weekly rotation report | Factor table → quadrants → ETF picks → HTML/DOCX/PDF export |
| Researcher | Backtest comparison | Monthly vs weekly rebalance, side-by-side Sharpe / drawdown |
| Researcher | Signal-news conflict check | Cross-validates golden-zone sectors against negative news |
| Researcher | Multi-agent debate | Quant + Macro + Risk debate, Coordinator fuses verdict |
| RM | Client portfolio | ETF list filtered by client risk level (R1–R5) with talking points |
| RM | Performance explanation | Client-ready narrative with evidence snippets |
| Compliance | Decision-trace review | Field-completeness audit on the latest trace |
| Compliance | Risk check | Concentration / liquidity / veto-list violation report |

---

## Quick start

### Requirements

- Python 3.10+
- A virtual environment is recommended

### Install

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Configure (already done for graders)

This repository ships with a working `.env` file and a code-level fallback
in `config/_demo_keys.py`, so a fresh clone is runnable out of the box —
no API key configuration required for evaluation.

If you want to plug in your own credentials, edit `.env` (it overrides
the bundled defaults):

```env
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://aihubmix.com/v1   # any OpenAI-compatible endpoint
OPENAI_MODEL=deepseek-v3.2

# Optional (each enables additional tools)
OPENAI_API_KEY_FALLBACK=...   # transparent retry when primary key fails
JINA_API_KEY=...              # Chinese web search & scrape
ALPHAVANTAGE_API_KEY=...      # global news + macro topics
TUSHARE_TOKEN=...             # A-share daily, ETF share, sector data
TUSHARE_API_URL=...           # custom Tushare proxy (e.g. xiaodefa.cn)
```

### Updating an existing clone

If you already cloned this repository earlier and just want to pull the
latest commits, also re-run the install command with `--upgrade` so that
the pinned dependencies (in particular `streamlit>=1.36.0`, required by
the `st.Page` / `st.navigation` API used in `frontend/app.py`) are kept
in sync.

```bash
git pull
pip install -r requirements.txt --upgrade
```

### Run

**Streamlit frontend (recommended — covers all 9 modules):**

```bash
streamlit run frontend/app.py
```

The frontend opens in English; flip the sidebar language radio to switch
the entire UI (and the Multi-Agent Debate panel) to 中文.

**CLI:**

```bash
# interactive
python main.py --role researcher --market a_share

# single query
python main.py --role researcher --market a_share \
    --query "Generate this week's A-share sector rotation report"

# export the latest trace to HTML / DOCX / PDF
python main.py --report
```

**MCP server** (optional, standalone):

```bash
# stdio (used by the agent by default)
python -m mcp_server.news_mcp_server

# HTTP, so MCP Inspector or another agent can connect
python -m mcp_server.news_mcp_server --http --port 8765
```

---

## Architecture

```
User query
    │
    ▼
┌───────────────────┐
│  Input Guardrail  │
└─────────┬─────────┘
          ▼
┌───────────────────┐
│      Router       │  structured task classification
└─────────┬─────────┘
          ▼
┌───────────────────┐
│      Planner      │  goal checklist + sub-task plan
└─────────┬─────────┘
          ▼
     ┌────┴───────────────────────────┐
     │                                │
┌────▼─────────────┐            ┌─────▼──────┐
│ Fixed subgraphs  │            │  Executor  │  ReAct loop with
│ (7 deterministic │            │ + ToolNode │  tool budget +
│  task chains)    │            │            │  repeat detection
└────┬─────────────┘            └─────┬──────┘
     │                                │
     └────────────┬───────────────────┘
                  ▼
          ┌───────────────────┐
          │    Reflection     │  critic → revise
          └─────────┬─────────┘
                    ▼
          ┌───────────────────┐
          │ Output Guardrail  │  + HITL gate for formal recommendations
          └─────────┬─────────┘
                    ▼
                Final answer
```

Cross-cutting layers (applied on every run):

- **Long-term Memory** — per-thread JSON profile injected into prompts
- **Goal Monitoring** — explicit sub-goal checklist per task
- **Resource Tracking** — tokens / $ / tool calls / latency per node
- **MCP** — news & macro tools accessible via Model Context Protocol

---

## Pattern coverage

| # | Pattern | Location |
|---|---|---|
| 1 | Prompt Chaining | `agent/prompts/prompt_builder.py` (base + role + task) |
| 2 | Routing | `agent/graph.py::router_node` + `agent/router_schema.py` |
| 3 | Parallelization | Backtest fan-out, news fan-out, 3 specialists in parallel |
| 4 | Reflection | `agent/patterns/reflection.py` (critic → revise loop) |
| 5 | Tool Use | `tools/` (30+ tools) + LangGraph `ToolNode` |
| 6 | Planning | `agent/graph.py::planner_node` |
| 7 | Multi-Agent | `agent/patterns/multi_agent.py` (Quant / Macro / Risk + Coordinator) |
| 8 | Long-term Memory | `agent/patterns/memory.py` (per-thread JSON, cross-session) |
| 10 | MCP | `mcp_server/` (FastMCP server + client) |
| 11 | Goal Setting & Monitoring | `agent/patterns/goal_monitor.py` |
| 12 | Exception Handling | Router fallback · tool budget · LLM key fallback |
| 14 | RAG | `agent/patterns/rag.py` + `tools/rag_tools.py` (FAISS + embeddings) |
| 15 | Inter-agent Communication | `agent/patterns/inter_agent.py` (Pydantic message schema) |
| 16 | Resource-aware Optimisation | `agent/patterns/resource_tracker.py` |
| 17 | Reasoning (Self-Consistency) | `agent/patterns/reasoning.py` (3-sample majority vote) |
| 18 | Guardrails | `agent/patterns/guardrails.py` (input + output + HITL) |

Patterns 9 and 13 from the syllabus are intentionally out of scope and
documented in `docs/AGENT_ARCHITECTURE.md`.

---

## Frontend modules

| Module | Purpose |
|---|---|
| Chat | Main conversation surface — Pattern badges, Goal checklist, Resource meter, Guardrail panel and Reflection timeline |
| Multi-Agent Debate | Live Quant / Macro / Risk panel with per-vote evidence, per-role model picker and bilingual cached output |
| Backtest Lab | Parallel monthly + weekly backtests with side-by-side metrics |
| Decision Trace | Browse the `traces/` directory with JSON preview and download |
| RAG Library | Query the internal research corpus (FAISS); rebuild the index on demand |
| Pattern Dashboard | Per-thread histogram of pattern invocations |
| HITL Approval | Compliance approval queue for formal recommendations |
| MCP Inspector | Handshake with the FastMCP server and call tools interactively |
| Settings | Long-term memory profile, model picker, IC overlay editor |

All nine modules are bilingual; canonical business values (market codes,
role names, quadrant labels) stay in their native form and are paired
with translated labels in the UI.

---

## Repository layout

```
.
├── main.py                     CLI entry point
├── requirements.txt
├── .env.example
│
├── agent/
│   ├── graph.py                LangGraph: Router / Planner / Executor / Reflector / Finalizer
│   ├── subgraph.py             Seven fixed-shape task subgraphs
│   ├── state.py                AgentState TypedDict (incl. output_language)
│   ├── router_schema.py        Structured router output schema
│   ├── patterns/               Pattern modules — one file each
│   └── prompts/                Base / role / task / router / reflection prompts
│
├── tools/                      30+ LangChain tools
├── data/providers/             AKShare / Tushare / yfinance adapters
├── data/cache/                 Local fund-flow CSV cache (git-ignored)
├── backtest/                   Rebalance loop + metrics
├── config/                     Market, factor, ETF-mapping, risk and model YAML
│
├── frontend/
│   ├── app.py                  Navigation + landing tour
│   ├── i18n.py                 EN / 中文 translation table + helpers
│   ├── _bootstrap.py           Shared sys.path / dotenv / language init
│   └── pages/                  Nine module pages
│
├── mcp_server/                 FastMCP news & macro server + client
├── scripts/                    Trace → HTML / DOCX / PDF exporter
├── templates/                  Weekly report / talking-point templates (EN + ZH)
├── docs/                       Architecture notes + RAG source corpus
└── traces/                     Runtime artefacts (git-ignored)
```

---

## Supported tasks

Thirteen task types are declared in `agent/prompts/task_prompts.py`. The
seven implemented as deterministic, auditable fixed subgraphs are:

- `research_weekly_report`
- `research_backtest_compare`
- `research_conflict_check`
- `rm_explain_performance`
- `rm_client_portfolio`
- `compliance_trace_review`
- `compliance_risk_check`

The remaining six (`research_overlay_adjustment`, `rm_batch_talking_points`,
`rm_market_specific`, `compliance_veto_audit`, `compliance_drawdown_check`,
`generic`) fall through to the ReAct Executor with tool budget and
repeat-call protection.

---

## Demo prompts

```bash
# Researcher
python main.py --role researcher --market a_share \
    --query "Generate this week's A-share sector rotation report"
python main.py --role researcher --market a_share \
    --query "Compare monthly vs weekly rebalance backtests"
python main.py --role researcher --market a_share \
    --query "Check if golden-zone sectors conflict with negative news"

# Relationship Manager
python main.py --role rm --market a_share \
    --query "Prepare an ETF portfolio for an R3 client"
python main.py --role rm --market a_share \
    --query "Explain last week's performance and draft a client talking point"

# Compliance
python main.py --role compliance --market a_share \
    --query "Audit the latest decision trace"
python main.py --role compliance --market a_share \
    --query "Run a concentration / liquidity risk check"

# Export the most recent trace
python main.py --report
```

The base system prompt mirrors the user's input language, so equivalent
Chinese queries work out of the box.

---

## Language handling

- **Default UI language is English.** Switch via the sidebar radio at any
  time; toggling it does not re-run the LLM — every Multi-Agent Debate
  result is translated once and cached in both languages.
- **Output language is threaded end-to-end** via
  `AgentState.output_language` so Quant / Macro / Risk specialists,
  fixed subgraphs and the generic executor all reply in the selected
  language on the next run.
- **Quick-start prompts ship with EN and ZH variants** so the response
  language stays consistent with the UI.

---

## Runtime artefacts

Running the agent creates the following under `traces/` (git-ignored):

- `traces/<date>/trace_*.json` — full state snapshot per run
- `traces/<date>/weekly_report.{html,docx,pdf}` — exported reports
- `traces/memory/<thread>.json` — long-term memory per user
- `traces/hitl/` — pending / approved / rejected HITL requests

The local fund-flow CSV cache lives at `data/cache/fund_flow/` and is
also git-ignored.

---

## Known limitations

- A-shares are the most complete market path; HK and US scaffolding is
  in place but not fully tuned.
- The `tushare` client is not fully thread-safe; the 4-way parallel
  macro fetch in `multi_agent_debate_node` uses an `_is_useful` filter
  and 4-way redundancy, so worst case is a sparser Macro report — no
  crash.
- There is no `pytest` suite yet; QA is via manual smoke runs of the
  Streamlit pages and the CLI demo prompts above.

---

## Acknowledgement

Coursework deliverable for **FTEC5660 — FinTech Project Workshop**, The
Chinese University of Hong Kong. Not licensed for redistribution outside
the course evaluation context.
