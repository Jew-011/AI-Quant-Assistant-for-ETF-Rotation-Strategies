"""Page 7 — Design Pattern Dashboard."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import pandas as pd
import streamlit as st

from agent.patterns.pattern_log import PATTERN_LOG
from frontend.i18n import t

st.title(t("pd.title"))
st.caption(t("pd.caption"))

threads = list(PATTERN_LOG._events.keys())  # type: ignore[attr-defined]
if not threads:
    st.info(t("pd.empty"))
    st.stop()

thread = st.selectbox(t("pd.thread"), options=threads)
events = PATTERN_LOG.get(thread)
summary = PATTERN_LOG.summary(thread)

st.metric(t("pd.metric.events"), len(events))

pattern_names = {
    1: "Prompt Chaining", 2: "Routing", 3: "Parallelization", 4: "Reflection",
    5: "Tool Use", 6: "Planning", 7: "Multi-Agent", 8: "Memory",
    10: "MCP", 11: "Goal Setting", 12: "Exception", 14: "RAG",
    15: "Inter-agent", 16: "Resource-aware", 17: "Reasoning", 18: "Guardrails",
}

df = pd.DataFrame(
    [
        {"pattern_id": pid, "pattern": pattern_names.get(pid, "?"), "count": cnt}
        for pid, cnt in sorted(summary.items())
    ]
)
if not df.empty:
    st.bar_chart(df.set_index("pattern")["count"])

with st.expander(t("pd.raw")):
    df_events = pd.DataFrame(events)
    st.dataframe(df_events, use_container_width=True, hide_index=True)
