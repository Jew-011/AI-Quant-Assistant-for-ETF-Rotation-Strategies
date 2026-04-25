"""Page 6 — HITL Approval Queue (Pattern 18)."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import streamlit as st

from agent.patterns.guardrails import decide_hitl, list_hitl_queue
from frontend.i18n import t

st.title(t("hitl.title"))
st.caption(t("hitl.caption"))

STATUS_KEYS = ["all", "pending", "approved", "rejected"]
STATUS_LABELS = {
    "all":      t("hitl.status.all"),
    "pending":  t("hitl.status.pending"),
    "approved": t("hitl.status.approved"),
    "rejected": t("hitl.status.rejected"),
}

status_filter = st.selectbox(
    t("hitl.filter"),
    options=STATUS_KEYS,
    format_func=lambda k: STATUS_LABELS[k],
    index=0,
)
queue = list_hitl_queue(status=status_filter)

col_list, col_detail = st.columns([1, 2])

with col_list:
    st.markdown(f"### {t('hitl.count', n=len(queue))}")
    if not queue:
        st.info(t("hitl.empty"))
    idx = st.radio(
        t("hitl.select"),
        options=list(range(len(queue))),
        format_func=lambda i: (
            f"{queue[i]['status']:>8} · {queue[i]['created_at']} · {queue[i]['task_key']} "
            f"({queue[i]['id'][:25]})"
        ),
        index=0 if queue else None,
    )

with col_detail:
    if queue and idx is not None:
        rec = queue[idx]
        st.markdown(f"### {t('hitl.request')} `{rec['id']}`")
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric(t("hitl.metric.status"),    rec.get("status", "?"))
        sc2.metric(t("hitl.metric.task"),      rec.get("task_key", "?"))
        sc3.metric(t("hitl.metric.requester"), rec.get("requester", "?"))

        with st.expander(t("hitl.payload"), expanded=True):
            st.json(rec.get("payload", {}))

        if rec.get("status") == "pending":
            st.markdown(f"### {t('hitl.decide')}")
            reviewer = st.text_input(t("hitl.reviewer"), value="compliance_officer")
            comment = st.text_area(t("hitl.comment"), height=80)
            a, b = st.columns(2)
            if a.button(t("common.approve"), type="primary", use_container_width=True):
                decide_hitl(rec["id"], approved=True, reviewer=reviewer, comment=comment)
                st.success(t("hitl.approved_ok"))
                st.rerun()
            if b.button(t("common.reject"), use_container_width=True):
                decide_hitl(rec["id"], approved=False, reviewer=reviewer, comment=comment)
                st.error(t("hitl.rejected_ok"))
                st.rerun()
        else:
            st.success(
                t(
                    "hitl.done",
                    decision=rec.get("decision"),
                    by=rec.get("decided_by"),
                    at=rec.get("decided_at"),
                    comment=rec.get("comment") or "—",
                )
            )
