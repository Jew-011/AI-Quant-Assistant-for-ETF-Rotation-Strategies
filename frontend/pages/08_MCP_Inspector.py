"""Page 8 — MCP Server Inspector (Pattern 10)."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import streamlit as st

from frontend.i18n import t
from mcp_server.news_mcp_client import call_mcp_tool, list_mcp_tools

st.title(t("mcp.title"))
st.caption(t("mcp.caption"))

mode = st.radio(t("mcp.transport"), ["stdio", "http"], horizontal=True)
url = st.text_input(t("mcp.url"), value="http://127.0.0.1:8765/mcp")

if "mcp_tools" not in st.session_state:
    st.session_state["mcp_tools"] = None

if st.button(t("mcp.discover"), type="primary"):
    with st.spinner(t("mcp.handshake")):
        tools = list_mcp_tools(mode=mode, url=url if mode == "http" else None)
    st.session_state["mcp_tools"] = tools

tools = st.session_state.get("mcp_tools")
if tools:
    st.success(t("mcp.found", n=len(tools)))
    for tool_entry in tools:
        with st.expander(f"{t('mcp.tool')}: {tool_entry['name']}"):
            st.caption(tool_entry.get("description", ""))
            if tool_entry.get("input_schema"):
                st.json(tool_entry["input_schema"])

    st.divider()
    st.markdown(f"### {t('mcp.invoke')}")
    names = [x["name"] for x in tools]
    pick = st.selectbox(t("mcp.tool"), names)
    args_text = st.text_area(
        t("mcp.args"),
        value='{"keywords": "semiconductor", "limit": 10}',
        height=120,
    )
    if st.button(t("mcp.call")):
        import json

        try:
            args = json.loads(args_text) if args_text.strip() else {}
        except Exception as exc:
            st.error(t("mcp.invalid_json", err=exc))
            args = None

        if args is not None:
            with st.spinner(t("mcp.calling")):
                out = call_mcp_tool(pick, args, mode=mode, url=url)
            st.markdown(f"#### {t('mcp.result')}")
            st.code(out[:8000], language="text")
else:
    st.info(t("mcp.wait"))
