# AI Quant Assistant for ETF Rotation Strategies — Architecture

---

## 1. Positioning

An **ETF sector-rotation advisory engine** for the wealth-management and
research desks of banks and brokerages.

The LLM acts as the "research brain": it parses user intent, dynamically
calls quantitative and information tools, reflects on the results, and
produces auditable ETF portfolio recommendations together with
institution-grade deliverables (weekly reports, talking-point cards,
Decision Traces).

Strict separation of duties:

* Factor calculations and backtests are executed precisely **in code**.
  The LLM does no math.
* The LLM owns intent understanding, tool routing, cross-validation of
  evidence, risk self-checks, and natural-language output.

---

## 2. User roles and target scenarios

### 2.1 Research desk

Owns the weekly / daily sector-rotation research process and report
production.

| Scenario | Agent behaviour |
|---|---|
| "Generate this week's A-share sector-rotation weekly report" | fetch market data → compute factors → quadrant scoring → check observation pool / veto list → ETF mapping → diff vs. last week → render the standard weekly-report template |
| "Add the consumer-recovery basket to the observation pool and rerun" | update config → re-run the signal pipeline → diff before/after explicitly |
| "Remove semiconductors from the veto list, see how signals change" | drop the rule → rerun → diff → annotate the change reason |
| "Backtest comparison: momentum window 12M vs 6M" | run the same backtest with two parameter sets → output Sharpe / MDD / annualised return comparison table |
| "Any sectors where the quant signal conflicts with the veto list this week?" | check whether any 'Golden Zone' sectors hit veto rules → if so, search news for additional context → flag the disagreement |

### 2.2 Relationship Manager / advisor

Client-facing role; needs profile-aware portfolios and talking-point
cards.

| Scenario | Agent behaviour |
|---|---|
| "Mr Zhang is risk level R2; build him an ETF portfolio with talking points" | take this week's signals → filter by R2 risk constraints → adjust weights → render a talking-point card |
| "The client asks why last week's recommendation went down — prep an explanation" | look up the previous Decision Trace → diff factor values vs this week → search related news → produce an attribution narrative |
| "Five client meetings this afternoon (R2/R3/R3/R4/R2), batch-generate cards" | per-client risk-aware adaptation → batch render |
| "Client only wants HK ETFs" | switch market config → run the signal pipeline within HK only → output an HK-only portfolio |

### 2.3 Risk / Compliance

Reviews agent output before it can be released to clients.

| Scenario | Agent behaviour |
|---|---|
| "Pull this week's Decision Trace" | output the full decision chain: factor values, quadrants, veto details, rule version, data timestamp |
| "Check whether this week's portfolio violates any risk rule" | iterate over institution-configured risk parameters (position cap, concentration, liquidity threshold...) and report each |
| "Which sectors were vetoed this week, and why?" | output the veto detail table (sector, rule ID, matched condition, reason) |
| "Worst monthly drawdown in backtest" | call the backtest tool → return the maximum drawdown and when it occurred |

---

## 3. Core agent loop: ReAct + Reflection

```
                       user request
                           │
                           ▼
                ┌───────────────────┐
                │    Reasoning      │ ◄──────────────────────┐
                │  LLM thinks:      │                        │
                │  what data and    │                        │
                │  tools do I need? │                        │
                │  what is next?    │                        │
                └────────┬──────────┘                        │
                         │                                   │
                         ▼                                   │
                ┌───────────────────┐                        │
                │    Action         │                        │
                │  call tools:      │                        │
                │  get_market_data  │                        │
                │  calc_factors     │                        │
                │  search_news      │                        │
                │  run_backtest     │                        │
                │  ...              │                        │
                └────────┬──────────┘                        │
                         │                                   │
                         ▼                                   │
                ┌───────────────────┐                        │
                │    Observation    │                        │
                │  receive results  │                        │
                └────────┬──────────┘                        │
                         │                                   │
                         ▼                                   │
                ┌───────────────────┐  problem found /       │
                │    Reflection     │  more info needed      │
                │  inspect output:  │ ───────────────────────┘
                │  · sensible?      │
                │  · risk-compliant?│
                │  · need more?     │
                └────────┬──────────┘
                         │ satisfied
                         ▼
                ┌───────────────────┐
                │  deliverable      │
                │  + Decision Trace │
                └───────────────────┘
```

The LLM may iterate this loop multiple times. Example: after computing
factors it spots an unusually strong signal in one sector → searches
news for confirmation → finds a negative item → flags the disagreement
→ adjusts the portfolio → re-runs the risk self-check → finalises.

---

## 4. Agent toolset

### 4.1 Quantitative tools (precise, executed in code)

| Tool | Input | Output |
|---|---|---|
| `get_market_data` | market, date range | sector index + ETF daily bars |
| `calc_factors_df` | price data, factor params | factor table (5 factors + trend + consensus per sector) |
| `score_quadrant_df` | factor scores, thresholds | quadrant label + score per sector |
| `map_etf` | sector list, ETF pool, filters | sector → recommended ETFs (code / size / volume) |
| `run_backtest` | historical signals, params | annualised return / MDD / Sharpe / equity curve |
| `get_decision_history` | date range | list of historical Decision Traces |
| `get_etf_flow_detail` | ETF code, days | per-day flow detail |

### 4.2 Information tools (evidence for LLM judgement)

| Tool | Input | Output |
|---|---|---|
| `search_news` | keywords, days, source | global news (Alpha Vantage / Jina) |
| `search_news_cn` | keywords | A-share / Chinese-language finance news |
| `get_macro_events` | days | macro event flash |
| `get_ic_overlay_config` | market | current observation-pool + veto-list config |

### 4.3 Output tools

| Tool | Input | Output |
|---|---|---|
| `save_decision_trace` | full decision payload | JSON archive |
| `generate_report` | structured data, template, role | weekly report / talking points / approval form (role-adapted) |

---

## 5. LLM responsibilities vs code responsibilities

| Stage | LLM does | Code does |
|---|---|---|
| Intent understanding | parse user request, choose tools and order | — |
| Data + factor compute | — | fetch data, compute factors (precisely) |
| Signal interpretation | inspect factor results, detect anomalies, decide whether more info is needed | — |
| Subjective judgement | cross-validate: factor signal vs. veto list vs. news; reason about disagreements | rule matching for the configured part |
| Portfolio review | reflection: concentration, style drift, compliance with risk params | — |
| Attribution | diff prior Decision Trace against current factor values; combine with news | pull historical data |
| Deliverable rendering | produce role-specific weekly report / talking points / approval form | template fill |

---

## 6. Factor system

### 6.1 Trend factors (price-based)

| Factor | Definition | Parameters | Source |
|---|---|---|---|
| MA Score | MA10 > MA20 > MA60 → +2; partial bull → +1; bear → −2; otherwise → 0 | windows: 10 / 20 / 60 | Huaxi Securities |
| 12M Momentum | cumulative return over the past 250 trading days, skipping the most recent 20 | window 250d, skip 20d | Huaxin Securities |

### 6.2 Consensus factors (volume / flow-based)

| Factor | Definition | Parameters | Source |
|---|---|---|---|
| ETF Flow Reversal | sum of retail net inflow into the sector ETF over the past 20 days, sign-inverted | window 20d | Zheshang Securities |
| Northbound / Smart Money | sum of northbound or large-order net inflow over the past 20 days | window 20d | Huaxin Securities |
| Volatility Convergence | std-dev of daily ETF flow over the past 20 days, sign-inverted | window 20d | internal research |

### 6.3 Composition

```
trend_score     = w1 * rank(MA Score) + w2 * rank(12M Momentum)
consensus_score = w3 * rank(ETF Flow Reversal)
                + w4 * rank(Northbound)
                + w5 * rank(Volatility Convergence)
```

Weights live in `config/factor_params.yaml`.

### 6.4 Four-quadrant classification

| Quadrant (Chinese key in data) | Condition | Action |
|---|---|---|
| 黄金配置区 (Golden Zone) | trend ↑ + consensus ↑ | overweight |
| 左侧观察区 (Left-side Watch) | trend ≈ + consensus ↑ + volatility convergence | watch for breakout |
| 高危警示区 (High-risk Warning) | trend ↑ + consensus ↓ | trim into strength |
| 垃圾规避区 (Avoidance) | trend ↓ + consensus ↓ | avoid |

The Chinese names are kept as data keys because they appear in the
DataFrame `quadrant` column and are matched verbatim by downstream
code; an English gloss is shown alongside in user-facing reports.

---

## 7. Multi-market support

When a user picks a market, the entire signal pipeline runs **inside
that market only** — no cross-market mixing.

| Configuration | A-share | HK | US |
|---|---|---|---|
| Industry classification | Shenwan Level-1 | Hang Seng | GICS Sectors |
| Consensus factor variant | Northbound | Southbound | Institutional holdings change |
| Data source | AKShare / Tushare | AKShare + yfinance | yfinance |

Same code, different YAML.

**Current implementation status.** The MVP ships with a fully populated
A-share sector list (31 Shenwan Level-1 industries). `market_us.yaml`
and `market_hk.yaml` are wired in as configuration extension points
with empty industry lists; the multi-agent debate node automatically
switches its global-news leg to English keywords + Alpha Vantage topics
for non-A-share markets (see `tools/global_news_strategy.py`).

---

## 8. Multi-agent collaboration (implemented)

The system can run a three-specialist debate followed by a Coordinator:

```
                     user request
                         │
                         ▼
               ┌──────────────────┐
               │   Coordinator    │
               │  dispatch + sync │
               └───┬──────┬───┬───┘
                   │      │   │
          ┌────────┘      │   └────────┐
          ▼               ▼            ▼
  ┌──────────────┐ ┌────────────┐ ┌────────────┐
  │ Quant        │ │  Macro     │ │   Risk     │
  │ Specialist   │ │ Strategist │ │  Manager   │
  │              │ │            │ │            │
  │ uses:        │ │ uses:      │ │ inspects:  │
  │ calc_factors │ │ search_news│ │ risk params│
  │ score_quad   │ │ get_macro  │ │ concentr / │
  │ map_etf      │ │ get_overlay│ │ liquidity  │
  └──────┬───────┘ └─────┬──────┘ └─────┬──────┘
         │               │              │
         └───────┬───────┘              │
                 ▼                      │
         ┌──────────────┐               │
         │ Coordinator  │◄──────────────┘
         │ aggregate    │
         │ resolve via  │
         │ self-cons.   │
         │ output+Trace │
         └──────────────┘
```

When the quant signal conflicts with the macro view, the Coordinator
aggregates each specialist's votes (Pattern 17 Self-Consistency) and
records both the disagreement and the resolution rationale into the
Decision Trace.

---

## 9. Configuration system (YAML)

Every parameter is institution-tunable. The Agent reads config at
runtime.

| File | Purpose |
|---|---|
| `market_*.yaml` | per-market: industry list, data source |
| `factor_params.yaml` | factor params: MA windows, momentum window, blend weights |
| `quadrant_thresholds.yaml` | four-quadrant cut-offs |
| `subjective_pool.yaml` | macro observation pool (external-demand / internal-demand / defensive baskets and their sectors) |
| `veto_list.yaml` | veto rules (rule ID, applicable sectors, condition, reason) |
| `etf_mapping.yaml` | sector → ETF map; liquidity / size filters |
| `risk_params.yaml` | institution risk params: position cap, concentration, liquidity threshold, client-risk-level constraints |
| `models.yaml` | LLM model catalog (id, label, provider, EN/ZH blurbs, prices) |
| `templates/*.md` | weekly report / talking points / approval form templates |

---

## 10. Decision Trace (audit log)

Every agent run writes a JSON archive containing:

| Field | Content |
|---|---|
| timestamp | run time |
| data_timestamp | data cut-off |
| config_version | configuration version |
| reasoning_chain | full LLM trace (each Reasoning / Action / Observation / Reflection step) |
| factor_scores | per-sector five factors + trend + consensus |
| quadrant_results | quadrant classification |
| veto_details | veto matches (sector, rule ID, reason) |
| etf_portfolio | final ETF portfolio + weights |
| risk_check | risk self-check result (pass / violations) |
| approval_status | HITL state (pending / approved / approver / time) |

Risk and Compliance can pull any historical Trace at any time.

---

## 11. Project layout

```
ETF_Assistant/
│
├── config/                         # YAML configuration
│   ├── market_a_share.yaml
│   ├── market_hk.yaml              # extension point
│   ├── market_us.yaml              # extension point
│   ├── factor_params.yaml
│   ├── quadrant_thresholds.yaml
│   ├── subjective_pool.yaml
│   ├── veto_list.yaml
│   ├── etf_mapping.yaml
│   ├── risk_params.yaml
│   └── models.yaml
│
├── tools/                          # Agent-callable tools
│   ├── data_tools.py               # get_market_data, get_etf_flow_detail
│   ├── factor_tools.py             # calc_factors_df
│   ├── scoring_tools.py            # score_quadrant_df
│   ├── filter_tools.py             # get_ic_overlay_config
│   ├── mapping_tools.py            # map_etf
│   ├── backtest_tools.py           # run_backtest
│   ├── news_tools.py               # search_news, search_news_cn, get_macro_events
│   ├── global_news_strategy.py     # market-aware global news query builder
│   ├── trace_tools.py              # save_decision_trace, get_decision_history
│   └── report_tools.py             # generate_report
│
├── agent/
│   ├── graph.py                    # LangGraph StateGraph (ReAct loop)
│   ├── subgraph.py                 # fixed subgraphs (weekly_prepare, debate, ...)
│   ├── state.py                    # AgentState definition
│   ├── router_schema.py            # Pydantic router output schema
│   ├── prompts/
│   │   ├── _lang.py                # central output-language directive
│   │   ├── base_prompt.py
│   │   ├── role_prompts.py
│   │   ├── task_prompts.py
│   │   ├── workflow_prompts.py
│   │   ├── router_prompts.py
│   │   ├── reflection_prompt.py
│   │   └── prompt_builder.py
│   └── patterns/                   # 18 agentic patterns
│       ├── multi_agent.py
│       ├── memory.py
│       ├── goal_monitor.py
│       ├── guardrails.py
│       ├── resource_tracker.py
│       └── pattern_log.py
│
├── backtest/
│   ├── pipeline.py
│   ├── portfolio.py
│   └── metrics.py
│
├── frontend/                       # Streamlit app (EN / ZH bilingual)
│   ├── app.py                      # st.navigation entry point
│   ├── i18n.py                     # translation table
│   ├── _models.py                  # model picker
│   └── pages/                      # 9 module pages
│
├── templates/                      # output templates
│   ├── weekly_report.md
│   ├── talking_points.md
│   └── approval_form.md
│
├── traces/                         # Decision Trace archive (per date)
│
├── main.py
├── requirements.txt
└── README.md
```

---

## 12. Tech stack

| Component | Choice |
|---|---|
| Agent framework | LangGraph (StateGraph + ToolNode + MemorySaver) |
| LLM | OpenAI / Claude / DeepSeek / Gemini via AIHubMix (OpenAI-compatible) |
| Model selection | runtime-switchable via `config/models.yaml` + sidebar picker |
| Data | AKShare + Tushare + yfinance |
| Compute | pandas + numpy |
| Schemas | Pydantic v2 |
| Configuration | YAML |
| Storage | JSON (Decision Trace) + on-disk memory store |
| MCP | news / macro / overlay tool surface (FastMCP) |
| Frontend | Streamlit (`st.navigation`, `st.Page`, `@st.dialog`) |
| RAG | FAISS-CPU (local index) |

---

## 13. Implementation roadmap

| Phase | Content | Status |
|---|---|---|
| P0 | tools + LangGraph ReAct loop + A-share factors + backtest | ✅ done |
| P1 | News MCP + LLM judgement + Reflection + Decision Trace | ✅ done |
| P2 | Multi-agent collaboration + role-adapted output + multi-market scaffolding | ✅ done (US/HK as extension points) |
| P3 | Streamlit UI + bilingual + HITL approval flow + model picker | ✅ done |
| P4 | US / HK industry catalogue + sector ETF list | open |
| P4 | Live ingestion of approver feedback into rolling memory | open |

---

## 14. Diagram annotations (for the deck)

1. **ReAct Loop** — LLM auto-iterates Reasoning → Action → Observation → Reflection.
2. **Decision Trace** — full reasoning chain is replayable, bound to data timestamp + rule version + approval record.
3. **Risk Guardrails** — institution-defined risk params; the agent self-checks during Reflection.
4. **Human-in-the-loop** — agent recommendations require approval before client release.
5. **Code stays code, LLM stays LLM** — factor / backtest computed precisely; LLM only reasons and judges.
