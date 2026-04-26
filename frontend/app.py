"""
AI Quant Assistant for ETF Rotation Strategies — Streamlit frontend.

Entry point. Uses ``st.navigation`` + ``st.Page`` so the sidebar page names
are translatable via the i18n layer, and renders a product-style landing
page (hero + feature cards + tour dialog) for first-time users.

Run with:
    streamlit run frontend/app.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

import streamlit as st

from frontend.i18n import init_lang, language_switcher, t
from frontend._models import init_model, model_switcher, current_model_meta

st.set_page_config(
    page_title="AI Quant Assistant — ETF Rotation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_lang()
init_model()

GITHUB_URL = "https://github.com/cjsmt/ETF_Assistant"

# File paths of the nine module pages (used by cards + page_links).
# Paths are kept relative to this entrypoint script so that Streamlit's
# st.Page() resolves them correctly on every platform, including macOS
# project paths that contain spaces.
PAGE_FILES = {
    "chat":     "pages/01_Chat.py",
    "trace":    "pages/02_Decision_Trace.py",
    "debate":   "pages/03_Multi_Agent_Debate.py",
    "rag":      "pages/04_RAG_Library.py",
    "bt":       "pages/05_Backtest_Lab.py",
    "hitl":     "pages/06_HITL_Approval.py",
    "patterns": "pages/07_Pattern_Dashboard.py",
    "mcp":      "pages/08_MCP_Inspector.py",
    "settings": "pages/09_Settings.py",
}


# ---------------------------------------------------------------------------
# Product tour — shown as a modal dialog with tabs per module.
# ---------------------------------------------------------------------------

@st.dialog(" ", width="large")  # title is filled by the markdown below
def _open_tour_dialog() -> None:
    st.markdown(f"## {t('tour.title')}")
    st.markdown(t("tour.intro"))

    tabs = st.tabs([
        t("tour.tab.chat"),
        t("tour.tab.debate"),
        t("tour.tab.bt"),
        t("tour.tab.trace"),
        t("tour.tab.rag"),
        t("tour.tab.patterns"),
        t("tour.tab.hitl"),
        t("tour.tab.mcp"),
        t("tour.tab.settings"),
    ])
    tour_keys = ["chat", "debate", "bt", "trace", "rag", "patterns", "hitl", "mcp", "settings"]

    for key, tab in zip(tour_keys, tabs):
        with tab:
            st.markdown(t("tour.section.what"))
            st.write(t(f"tour.{key}.what"))
            st.markdown(t("tour.section.when"))
            st.write(t(f"tour.{key}.when"))
            st.markdown(t("tour.section.try"))
            st.markdown(t(f"tour.{key}.try"))
            st.divider()
            st.page_link(PAGE_FILES[key], label=t("card.open"), icon="➡️")

    st.divider()
    if st.button(t("tour.close"), use_container_width=True):
        st.rerun()


# ---------------------------------------------------------------------------
# Home / landing page
# ---------------------------------------------------------------------------

def _feature_card(icon: str, key: str, page_file: str) -> None:
    """Render one bordered card inside the current column."""
    with st.container(border=True, height=200):
        st.markdown(f"### {icon} {t(f'card.{key}.title')}")
        st.caption(t(f"card.{key}.desc"))
        st.page_link(page_file, label=t("card.open"), icon="➡️")


def home() -> None:
    # --- Hero --------------------------------------------------------------
    st.title(t("app.title"))
    st.markdown(
        f"<p style='font-size:1.05rem; color:#9aa3b2; margin-top:-0.4rem;'>"
        f"{t('hero.subtitle')}</p>",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(t("hero.metric.patterns"), "14+")
    m2.metric(t("hero.metric.modules"),  "9")
    m3.metric(t("hero.metric.roles"),    "3")
    m4.metric(t("hero.metric.tools"),    "30+")

    st.write("")  # small vertical spacer
    cta1, cta2, cta3, _spacer = st.columns([1, 1, 1, 2])
    with cta1:
        st.page_link(PAGE_FILES["chat"], label=t("hero.cta.start"),
                     icon="💬", use_container_width=True)
    with cta2:
        if st.button(t("hero.cta.tour"), type="primary", use_container_width=True, icon="🧭"):
            _open_tour_dialog()
    with cta3:
        st.link_button(t("hero.cta.github"), GITHUB_URL,
                       use_container_width=True, icon="🔗")

    st.divider()

    # --- Feature grid 3×3 --------------------------------------------------
    row1 = st.columns(3, gap="medium")
    with row1[0]: _feature_card("💬", "chat",    PAGE_FILES["chat"])
    with row1[1]: _feature_card("⚔️", "debate",  PAGE_FILES["debate"])
    with row1[2]: _feature_card("📈", "bt",      PAGE_FILES["bt"])

    row2 = st.columns(3, gap="medium")
    with row2[0]: _feature_card("📜", "trace",   PAGE_FILES["trace"])
    with row2[1]: _feature_card("📚", "rag",     PAGE_FILES["rag"])
    with row2[2]: _feature_card("📡", "patterns",PAGE_FILES["patterns"])

    row3 = st.columns(3, gap="medium")
    with row3[0]: _feature_card("🛡️", "hitl",    PAGE_FILES["hitl"])
    with row3[1]: _feature_card("🔌", "mcp",     PAGE_FILES["mcp"])
    with row3[2]: _feature_card("⚙️", "settings",PAGE_FILES["settings"])

    st.divider()

    # --- Collapsible technical info ---------------------------------------
    with st.expander(t("app.section.patterns"), expanded=False):
        import pandas as pd
        pattern_table = pd.DataFrame(
            [
                ["1  Prompt Chaining",           "✅", "prompts/prompt_builder.py"],
                ["2  Routing",                   "✅", "graph.router_node + router_schema"],
                ["3  Parallelization",           "✅", "subgraph.backtest_compare / conflict_check / multi_agent"],
                ["4  Reflection",                "✅", "patterns/reflection.py (real critic→revise)"],
                ["5  Tool Use",                  "✅", "tools/ + ToolNode"],
                ["6  Planning",                  "✅", "graph.planner_node"],
                ["7  Multi-Agent",               "✅", "patterns/multi_agent.py (Quant+Macro+Risk+Coordinator)"],
                ["8  Memory",                    "✅", "patterns/memory.py (long-term JSON)"],
                ["10 MCP",                       "✅", "mcp_server/ (FastMCP server + client)"],
                ["11 Goal Setting & Monitoring", "✅", "patterns/goal_monitor.py"],
                ["12 Exception Handling",        "✅", "router fallback + tool budget + repeat detection"],
                ["14 RAG",                       "✅", "patterns/rag.py + tools/rag_tools.py"],
                ["15 Inter-agent Comm.",         "✅", "patterns/inter_agent.py (pydantic msg schema)"],
                ["16 Resource-aware Optim.",     "✅", "patterns/resource_tracker.py (token/cost/latency)"],
                ["17 Reasoning (Self-Consistency)", "✅", "patterns/reasoning.py (3-sample vote)"],
                ["18 Guardrails",                "✅", "patterns/guardrails.py + HITL queue"],
            ],
            columns=[t("app.table.pattern"), t("app.table.status"), t("app.table.where")],
        )
        st.dataframe(pattern_table, use_container_width=True, hide_index=True)

    with st.expander(t("app.section.quickstart"), expanded=False):
        st.code(
            "pip install -r requirements.txt\n"
            "cp .env.example .env   # fill in keys\n"
            "streamlit run frontend/app.py",
            language="bash",
        )


# ---------------------------------------------------------------------------
# Sidebar — language switcher + persistent Help button + environment info.
# ---------------------------------------------------------------------------

with st.sidebar:
    language_switcher()
    st.divider()
    model_switcher()
    st.divider()
    if st.button(t("help.sidebar"), icon="❓", use_container_width=True):
        _open_tour_dialog()

# ---------------------------------------------------------------------------
# Navigation — sections grouped, titles pulled through ``t()``.
# ---------------------------------------------------------------------------

pages = {
    t("nav.section.workspace"): [
        st.Page(home, title=t("nav.home"), icon="🏠", default=True, url_path="home"),
        st.Page(PAGE_FILES["chat"],   title=t("nav.chat"),   icon="💬", url_path="chat"),
        st.Page(PAGE_FILES["debate"], title=t("nav.debate"), icon="⚔️", url_path="debate"),
        st.Page(PAGE_FILES["bt"],     title=t("nav.bt"),     icon="📈", url_path="backtest"),
    ],
    t("nav.section.insight"): [
        st.Page(PAGE_FILES["trace"],    title=t("nav.trace"),    icon="📜", url_path="trace"),
        st.Page(PAGE_FILES["rag"],      title=t("nav.rag"),      icon="📚", url_path="rag"),
        st.Page(PAGE_FILES["patterns"], title=t("nav.patterns"), icon="📡", url_path="patterns"),
    ],
    t("nav.section.admin"): [
        st.Page(PAGE_FILES["hitl"],     title=t("nav.hitl"),     icon="🛡️", url_path="hitl"),
        st.Page(PAGE_FILES["mcp"],      title=t("nav.mcp"),      icon="🔌", url_path="mcp"),
        st.Page(PAGE_FILES["settings"], title=t("nav.settings"), icon="⚙️", url_path="settings"),
    ],
}

with st.sidebar:
    st.divider()
    st.markdown(f"### {t('app.sidebar.env')}")
    _meta = current_model_meta()
    _active_label = (
        f"{_meta.label} ({_meta.provider})" if _meta is not None
        else os.getenv("OPENAI_MODEL", "not set")
    )
    st.markdown(
        f"- {t('model.active')}: `{_active_label}`\n"
        f"- MCP mode: `{os.getenv('ETF_MCP_MODE', 'stdio')}`"
    )

nav = st.navigation(pages, position="sidebar", expanded=True)
nav.run()
