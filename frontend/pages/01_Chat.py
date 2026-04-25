"""Page 1 — Chat with the agent."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import streamlit as st

from agent.graph import run_agent
from agent.patterns.pattern_log import PATTERN_LOG
from frontend._models import current_model
from frontend._progress_view import progress_view
from frontend.i18n import current_lang, t

st.title(t("chat.title"))

PATTERN_NAMES = {
    1: "Prompt Chaining", 2: "Routing", 3: "Parallelization", 4: "Reflection",
    5: "Tool Use", 6: "Planning", 7: "Multi-Agent", 8: "Memory",
    10: "MCP", 11: "Goal Setting", 12: "Exception", 14: "RAG",
    15: "Inter-agent", 16: "Resource-aware", 17: "Reasoning", 18: "Guardrails",
}

# Reverse-lookup labels for market / role (labels shown in UI, values kept in English for backend).
MARKET_LABELS = {
    "a_share": t("common.market.a_share"),
    "hk":      t("common.market.hk"),
    "us":      t("common.market.us"),
}
ROLE_LABELS = {
    "researcher": t("common.role.researcher"),
    "rm":         t("common.role.rm"),
    "compliance": t("common.role.compliance"),
}

with st.sidebar:
    st.header(t("common.run_config"))
    market = st.selectbox(
        t("common.market"),
        options=list(MARKET_LABELS.keys()),
        format_func=lambda k: MARKET_LABELS[k],
        index=0,
    )
    role = st.selectbox(
        t("common.role"),
        options=list(ROLE_LABELS.keys()),
        format_func=lambda k: ROLE_LABELS[k],
        index=0,
    )
    client_risk = None
    if role == "rm":
        client_risk = st.selectbox(t("common.client_risk"), ["R1", "R2", "R3", "R4", "R5"], index=2)
    thread_id = st.text_input(t("common.thread_id"), value=st.session_state.get("thread_id", "demo_user"))
    st.session_state["thread_id"] = thread_id

    st.divider()
    st.markdown(f"### {t('chat.quick_prompts')}")
    # Both the button label and the query sent to the agent are translated,
    # so English users get an English query (and thus an English response)
    # and Chinese users get the original Chinese wording.
    quick_prompts = [
        ("chat.qp.weekly",     "chat.qq.weekly"),
        ("chat.qp.debate",     "chat.qq.debate"),
        ("chat.qp.backtest",   "chat.qq.backtest"),
        ("chat.qp.conflict",   "chat.qq.conflict"),
        ("chat.qp.r3",         "chat.qq.r3"),
        ("chat.qp.compliance", "chat.qq.compliance"),
        ("chat.qp.rag",        "chat.qq.rag"),
        ("chat.qp.guardrail",  "chat.qq.guardrail"),
    ]
    for label_key, query_key in quick_prompts:
        if st.button(t(label_key), use_container_width=True, key=f"qp_{label_key}"):
            st.session_state["pending_prompt"] = t(query_key)

if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "last_pattern_events" not in st.session_state:
    st.session_state["last_pattern_events"] = []

main_col, side_col = st.columns([3, 2])

with main_col:
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input(t("chat.input.placeholder"))
    if "pending_prompt" in st.session_state:
        prompt = st.session_state.pop("pending_prompt")

    if prompt:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            try:
                with progress_view() as cb:
                    result = run_agent(
                        user_input=prompt,
                        market=market,
                        role=role,
                        thread_id=thread_id,
                        client_risk_level=client_risk,
                        verbose=False,
                        return_state=True,
                        output_language=current_lang(),
                        model_name=current_model(),
                        progress_cb=cb,
                    )
                answer = result["final_answer"] if isinstance(result, dict) else str(result)
                if isinstance(result, dict):
                    st.session_state["last_state"] = result["state"]
                    st.session_state["last_pattern_events"] = result["pattern_events"]
                    st.session_state["last_pattern_summary"] = result["pattern_summary"]
                    st.session_state["last_resource_usage"] = result["resource_usage"]
            except Exception as exc:
                answer = f"{t('chat.err.failed')}: {exc}"
            st.markdown(answer)
        st.session_state["messages"].append({"role": "assistant", "content": answer})
        st.rerun()

with side_col:
    st.markdown(f"### {t('chat.side.patterns')}")
    summary = st.session_state.get("last_pattern_summary") or {}
    if summary:
        chips = " ".join(
            f":blue-badge[Pattern {pid} · {PATTERN_NAMES.get(pid, '?')} × {cnt}]"
            for pid, cnt in sorted(summary.items())
        )
        st.markdown(chips)
    else:
        st.caption(t("chat.side.patterns_empty"))

    with st.expander(t("chat.side.goal")):
        goal = (st.session_state.get("last_state") or {}).get("goal_state") or {}
        if goal:
            st.markdown(f"**{t('chat.side.goal.objective')}**: {goal.get('objective')}")
            pct = int((st.session_state.get('last_state') or {}).get('goal_progress', 0) * 100)
            st.progress(pct / 100.0, text=f"{pct}{t('chat.side.goal.pct')}")
            for sg in goal.get("sub_goals", []):
                mark = "✅" if sg.get("satisfied") else "⬜"
                st.markdown(f"{mark} **{sg.get('id')}** — {sg.get('description')}")
        else:
            st.caption(t("chat.side.goal.none"))

    with st.expander(t("chat.side.resource")):
        usage = st.session_state.get("last_resource_usage") or {}
        if usage:
            st.metric(t("chat.side.resource.llm"), usage.get("llm_calls", 0))
            cola, colb = st.columns(2)
            cola.metric(t("chat.side.resource.tok"), f"{usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)}")
            colb.metric(t("chat.side.resource.cost"), f"${usage.get('estimated_cost_usd', 0):.5f}")
            st.metric(t("chat.side.resource.tool"), usage.get("tool_calls", 0))
            if usage.get("tools_breakdown"):
                st.caption(t("chat.side.resource.breakdown"))
                st.json(usage["tools_breakdown"])
        else:
            st.caption(t("chat.side.resource.none"))

    with st.expander(t("chat.side.guardrail")):
        state = st.session_state.get("last_state") or {}
        st.caption(f"**{t('chat.side.guardrail.in')}**")
        st.json(state.get("input_guardrail") or {})
        st.caption(f"**{t('chat.side.guardrail.out')}**")
        st.json(state.get("output_guardrail") or {})
        if state.get("hitl_request"):
            hitl_id = state["hitl_request"].get("id")
            st.warning(f"{t('chat.side.guardrail.hitl')} `{hitl_id}`")

    with st.expander(t("chat.side.reflect")):
        state = st.session_state.get("last_state") or {}
        rounds = state.get("reflection_rounds") or []
        if rounds:
            for r in rounds:
                crit = r.get("critique", {})
                st.markdown(
                    f"**{t('chat.side.reflect.round')} {r.get('round')}** — "
                    f"{t('chat.side.reflect.score')} **{crit.get('score'):.2f}** "
                    f"(passes_quality_bar={crit.get('passes_quality_bar')})"
                )
                st.write(crit.get("summary", ""))
                for i in crit.get("issues", [])[:5]:
                    st.markdown(
                        f"- [{i.get('severity', '')}] *{i.get('category', '')}* — "
                        f"{i.get('comment', '')} → {i.get('suggestion', '')}"
                    )
                if r.get("revised"):
                    st.caption(t("chat.side.reflect.revised"))
        else:
            st.caption(t("chat.side.reflect.none"))

    with st.expander(t("chat.side.events")):
        events = st.session_state.get("last_pattern_events") or []
        if events:
            for ev in events[-40:]:
                st.caption(
                    f"[{ev['ts']}] P{ev['pattern_id']} {ev['pattern_name']} · "
                    f"{ev['node']} — {ev['detail']}"
                )
        else:
            st.caption(t("chat.side.events.none"))
