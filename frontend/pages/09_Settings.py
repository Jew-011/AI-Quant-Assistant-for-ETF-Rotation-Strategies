"""Page 9 — Settings (Memory + Overlay config)."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import os

import streamlit as st

from agent.patterns.memory import list_all_threads, load_memory, save_memory, update_profile
from frontend._bootstrap import PROJECT_ROOT
from frontend._models import (
    SPECIALIST_ROLES,
    current_specialist_models,
    default_specialist_models,
    load_models,
    set_specialist_model,
    sync_specialist_models_to_env,
)
from frontend.i18n import current_lang, t

st.title(t("cfg.title"))

tab_mem, tab_models, tab_overlay = st.tabs([
    t("cfg.tab.memory"),
    t("cfg.tab.models"),
    t("cfg.tab.overlay"),
])

with tab_mem:
    st.caption(t("cfg.mem.caption"))
    threads = list_all_threads()
    if not threads:
        st.info(t("cfg.mem.empty"))
    else:
        thread = st.selectbox(t("cfg.mem.thread"), threads)
        mem = load_memory(thread)
        st.markdown(f"### {t('cfg.mem.profile')}")
        c1, c2, c3 = st.columns(3)
        risk = c1.selectbox(
            t("cfg.mem.risk"),
            ["", "R1", "R2", "R3", "R4", "R5"],
            index=(["", "R1", "R2", "R3", "R4", "R5"].index(mem.profile.risk_level or "")),
        )
        market = c2.selectbox(
            t("cfg.mem.market"),
            ["", "a_share", "hk", "us"],
            index=(["", "a_share", "hk", "us"].index(mem.profile.preferred_market or "")),
        )
        note = c3.text_input(t("cfg.mem.note"), value=mem.profile.note)
        if st.button(t("cfg.mem.save_profile")):
            update_profile(thread, risk_level=risk or None, preferred_market=market or None, note=note)
            st.success(t("cfg.mem.saved"))

        st.markdown(f"### {t('cfg.mem.history')}")
        import pandas as pd

        if mem.query_history:
            st.dataframe(pd.DataFrame(mem.query_history[-30:]), use_container_width=True, hide_index=True)
        else:
            st.caption(t("cfg.mem.no_history"))

        st.markdown(f"### {t('cfg.mem.tasks')}")
        if mem.task_counter:
            st.bar_chart(mem.task_counter)
        else:
            st.caption(t("cfg.mem.no_tasks"))

with tab_models:
    st.caption(t("cfg.models.caption"))

    models = load_models()
    if not models:
        st.warning("models.yaml is empty — cannot pick specialist models.")
    else:
        cur = current_specialist_models()
        ids = [m.id for m in models]
        label_for = {m.id: f"{m.label}  ·  {m.provider}" for m in models}
        meta_for  = {m.id: m for m in models}
        ui_lang = current_lang()

        cols = st.columns(2)
        new_assignment: dict[str, str] = {}

        for i, role in enumerate(SPECIALIST_ROLES):
            with cols[i % 2]:
                st.markdown(f"#### {t(f'cfg.models.role.{role}')}")
                st.caption(t(f"cfg.models.role.{role}.help"))
                cur_id = cur.get(role) or ids[0]
                if cur_id not in ids:
                    cur_id = ids[0]
                picked = st.selectbox(
                    label=t(f"cfg.models.role.{role}"),
                    options=ids,
                    index=ids.index(cur_id),
                    format_func=lambda i: label_for.get(i, i),
                    key=f"_specialist_model_{role}",
                    label_visibility="collapsed",
                )
                meta = meta_for.get(picked)
                if meta:
                    st.caption(meta.blurb(ui_lang))
                    st.caption(
                        t(
                            "model.price",
                            pin=f"{meta.price_in*1000:.2f}",
                            pout=f"{meta.price_out*1000:.2f}",
                        )
                    )
                new_assignment[role] = picked

        # Cost preview: rough per-debate estimate (3 specialists + 1 coordinator,
        # ~5K tokens each = 5K in + 1K out per call) so users can see what each
        # change costs them.
        per_call_in, per_call_out = 5.0, 1.0  # in K-tokens
        cost = 0.0
        for role, mid in new_assignment.items():
            m = meta_for.get(mid)
            if m:
                cost += per_call_in * m.price_in + per_call_out * m.price_out

        st.caption(t("cfg.models.cost.hint", cost=cost))

        c1, c2 = st.columns([1, 1])
        if c1.button(t("cfg.models.save"), type="primary", use_container_width=True):
            for role, mid in new_assignment.items():
                set_specialist_model(role, mid)
            sync_specialist_models_to_env()
            st.success(t("cfg.models.saved"))
            st.rerun()

        if c2.button(t("cfg.models.reset"), use_container_width=True):
            defaults = default_specialist_models()
            for role, mid in defaults.items():
                set_specialist_model(role, mid)
            sync_specialist_models_to_env()
            st.success(t("cfg.models.saved"))
            st.rerun()

        st.divider()
        st.markdown(f"**{t('cfg.models.preview')}**")
        live = current_specialist_models()
        rows = [
            {
                "Role": t(f"cfg.models.role.{role}"),
                "Model": label_for.get(live.get(role, ""), live.get(role, "")),
                "Env var": f"OPENAI_MODEL_{role.upper()}",
            }
            for role in SPECIALIST_ROLES
        ]
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


with tab_overlay:
    st.caption(t("cfg.overlay.caption"))
    config_dir = os.path.join(PROJECT_ROOT, "config")
    editable = [
        "subjective_pool.yaml",
        "veto_list.yaml",
        "etf_mapping.yaml",
        "factor_params.yaml",
        "risk_params.yaml",
        "quadrant_thresholds.yaml",
    ]
    available = [f for f in editable if os.path.isfile(os.path.join(config_dir, f))]
    if not available:
        st.warning(t("cfg.overlay.none", path=config_dir))
    else:
        picked = st.selectbox(t("cfg.overlay.file"), available)
        path = os.path.join(config_dir, picked)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        edited = st.text_area(picked, value=content, height=500)
        if st.button(t("cfg.overlay.save", name=picked)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(edited)
            st.success(t("cfg.overlay.saved", name=picked))
