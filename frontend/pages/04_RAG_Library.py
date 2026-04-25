"""Page 4 — RAG Research Library (Pattern 14)."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import os

import streamlit as st

from agent.patterns.rag import rebuild_rag_index, search_research_library
from frontend._bootstrap import DOCS_DIR
from frontend.i18n import t

st.title(t("rag.title"))
st.caption(t("rag.caption"))

col_search, col_admin = st.columns([3, 1])

with col_admin:
    st.markdown(f"### {t('rag.index')}")
    files = []
    for root, _, names in os.walk(DOCS_DIR):
        if "rag_index" in root:
            continue
        for n in names:
            if n.lower().endswith((".md", ".txt")):
                files.append(os.path.relpath(os.path.join(root, n), DOCS_DIR))
    st.caption(t("rag.index.files", n=len(files)))
    for f in files:
        st.markdown(f"- `{f}`")
    if st.button(t("rag.index.rebuild"), use_container_width=True):
        with st.spinner(t("rag.index.rebuilding")):
            result = rebuild_rag_index()
        st.success(t("rag.index.rebuilt", info=result))

with col_search:
    st.markdown(f"### {t('rag.search')}")
    query = st.text_input(
        t("rag.ask"),
        value=t("rag.ask.default"),
        placeholder=t("rag.ask.placeholder"),
    )
    k = st.slider(t("rag.topk"), min_value=1, max_value=10, value=4)

    if query:
        with st.spinner(t("rag.retrieving")):
            results = search_research_library(query, k=k, thread_id="rag_page")
        if not results:
            st.warning(t("rag.no_chunks"))
        else:
            st.success(t("rag.n_chunks", n=len(results)))
            for i, c in enumerate(results, 1):
                with st.expander(
                    f"[{i}] {c.source} · score={c.score:.4f}", expanded=(i == 1)
                ):
                    st.write(c.content)
