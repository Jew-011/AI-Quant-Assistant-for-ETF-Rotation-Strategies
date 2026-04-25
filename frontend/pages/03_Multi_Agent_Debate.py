"""Page 3 — Multi-Agent Debate viewer (Pattern 7/15/17)."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

import pandas as pd
import streamlit as st

from agent._progress import chain_callbacks
from agent.patterns.multi_agent import DebateInputs, run_debate_parallel
from agent.patterns.pattern_log import PATTERN_LOG
from agent.patterns.translate import make_bilingual_debate
from agent.subgraph import (
    calc_factors_df,
    fetch_debate_evidence,
    score_quadrant_df,
    _summarize_quadrants,
)
from frontend._debate_panel import DebateCardBoard
from frontend._models import (
    SPECIALIST_ROLES,
    current_model,
    current_specialist_models,
    load_models,
    set_specialist_model,
)
from frontend._progress_view import progress_view
from frontend.i18n import current_lang, t
from tools.filter_tools import get_ic_overlay_config

st.title(t("debate.title"))
st.caption(t("debate.caption"))

# ---------------------------------------------------------------------------
# Live debate panel — 3 specialist cards that animate during the parallel run.
# Always rendered (even before user clicks Run) so the user can see WHO is
# going to debate before the debate starts.
# ---------------------------------------------------------------------------
st.markdown(f"#### {t('debate.board.title')}")
_specialist_models = current_specialist_models()
board = DebateCardBoard(
    roles=("quant", "macro", "risk"),
    role_models={
        "quant": _specialist_models.get("quant", ""),
        "macro": _specialist_models.get("macro", ""),
        "risk":  _specialist_models.get("risk", ""),
    },
)
board.render_initial()
st.caption(
    t("debate.board.coordinator_hint",
      model=_specialist_models.get("coordinator", "—"))
)

MARKET_LABELS = {
    "a_share": t("common.market.a_share"),
    "hk":      t("common.market.hk"),
    "us":      t("common.market.us"),
}

with st.sidebar:
    st.header(t("debate.sidebar.header"))
    market = st.selectbox(
        t("common.market"),
        options=list(MARKET_LABELS.keys()),
        format_func=lambda k: MARKET_LABELS[k],
        index=0,
    )
    risk = st.selectbox(t("common.client_risk"), ["N/A", "R1", "R2", "R3", "R4", "R5"], index=3)
    user_q = st.text_area(
        t("debate.question"),
        value=t("debate.question.default"),
        height=120,
    )

    # ------------------------------------------------------------------
    # Quick model assignment — same as Settings → Specialist models, but
    # in-place so the user doesn't have to navigate away. Changes apply
    # immediately to the next debate run (and to the model badges on the
    # cards above, via st.rerun()).
    # ------------------------------------------------------------------
    with st.expander(t("debate.sidebar.models.header"), expanded=False):
        st.caption(t("debate.sidebar.models.caption"))
        _all_models = load_models()
        if not _all_models:
            st.warning("models.yaml is empty.")
        else:
            _ids = [m.id for m in _all_models]
            _label_for = {m.id: f"{m.label}  ·  {m.provider}" for m in _all_models}
            _live = current_specialist_models()
            for role in SPECIALIST_ROLES:
                cur_id = _live.get(role) or _ids[0]
                if cur_id not in _ids:
                    cur_id = _ids[0]
                picked = st.selectbox(
                    label=t(f"cfg.models.role.{role}"),
                    options=_ids,
                    index=_ids.index(cur_id),
                    format_func=lambda i: _label_for.get(i, i),
                    key=f"_sidebar_specialist_{role}",
                )
                if picked != _live.get(role):
                    set_specialist_model(role, picked)
                    st.rerun()
            st.caption(t("debate.sidebar.models.tip"))

    run_btn = st.button(t("debate.run"), use_container_width=True, type="primary")

if run_btn:
    lang = current_lang()
    with progress_view() as progress_cb:
        # Fan-out: progress events drive both the card animation AND the log.
        cb = chain_callbacks(board.as_progress_callback(), progress_cb)
        cb("debate.evidence", t("progress.debate.evidence"), "info")
        df = calc_factors_df(market=market)
        if df.empty:
            cb("failed", t("debate.err.empty_factor"), "error")
            st.error(t("debate.err.empty_factor"))
            st.stop()
        quadrant_df = score_quadrant_df(df)
        _, quadrant_summary = _summarize_quadrants(quadrant_df)
        factor_summary = df.head(10).to_string(index=False)
        overlay = get_ic_overlay_config.invoke({"market": market})

        # Pull macro events + sector news so the Macro specialist actually
        # sees something. Without this it falls back to "no macro data" and
        # produces those bland "see observation pool" reports the user has
        # been asking about. Reuses the SAME helper as the LangGraph flow,
        # so the Debate page and the full agent are in lockstep.
        cb("debate.evidence", t("progress.debate.evidence"), "info")
        golden = (
            quadrant_df[quadrant_df["quadrant"] == "黄金配置区"]["industry"]
            .head(4).tolist()
        )
        sector_kw = ", ".join(golden[:3]) if golden else market
        macro_events, news_text, _ev_stats = fetch_debate_evidence(
            market=market, sector_kw=sector_kw,
        )

        inputs = DebateInputs(
            market=market,
            factor_summary=factor_summary,
            quadrant_summary=quadrant_summary,
            observation_pool=overlay,
            veto_list_text="see overlay" if lang == "en" else "见 overlay",
            macro_events=macro_events,
            news_text=news_text,
            client_risk_level=None if risk == "N/A" else risk,
            user_question=user_q,
            output_language=lang,
        )
        # Heterogeneous ensemble: each specialist may run on a different model
        # (set in the Settings page). Falls back to the global model picker.
        specialist_models = current_specialist_models()
        result = run_debate_parallel(
            inputs,
            thread_id="debate_page",
            model=current_model(),
            progress_cb=cb,
            models_per_role={
                "quant": specialist_models.get("quant"),
                "macro": specialist_models.get("macro"),
                "risk":  specialist_models.get("risk"),
            },
            coordinator_model=specialist_models.get("coordinator"),
        )

        # Bilingual mirror: translate the result into the OTHER language with
        # a cheap fast model so future UI-language switches are instant. This
        # eliminates the "stale language" warning entirely on success.
        cb("debate.translate", t("progress.debate.translate"), "info")
        bilingual = make_bilingual_debate(result, primary_lang=lang)
        translation_ok = (
            bilingual.get("en") is not None
            and bilingual.get("zh") is not None
            and bilingual.get("en") is not bilingual.get("zh")  # not the silent-fallback case
        )
        cb("debate.complete", t("progress.debate.complete"), "success")

    # Cache both copies. ``last_debate`` always points at the active-lang
    # version so legacy code paths keep working unchanged.
    st.session_state["last_debate_bilingual"] = bilingual
    st.session_state["last_debate"] = bilingual.get(lang, result)
    st.session_state["last_debate_lang"] = lang
    st.session_state["last_debate_translation_ok"] = translation_ok
    # Replace the live cards with each specialist's verdict summary.
    board.render_results(st.session_state["last_debate"].get("reports", {}))
    if translation_ok:
        st.toast(t("debate.bilingual.ready"), icon="🌐")
    else:
        st.toast(t("debate.translate_failed"), icon="⚠️")
elif "last_debate" in st.session_state:
    # Page reload — pick the cached copy in the CURRENT language if we have
    # a bilingual cache; otherwise restore whatever's there.
    bilingual = st.session_state.get("last_debate_bilingual") or {}
    active = bilingual.get(current_lang()) or st.session_state["last_debate"]
    st.session_state["last_debate"] = active
    board.render_results(active.get("reports", {}))

# Show the stale-language warning ONLY when bilingual translation failed
# (in which case we genuinely don't have a copy in the new UI lang).
if "last_debate" in st.session_state:
    bilingual = st.session_state.get("last_debate_bilingual") or {}
    cur_lang = current_lang()
    if not bilingual.get(cur_lang):
        cached_lang = st.session_state.get("last_debate_lang")
        if cached_lang and cached_lang != cur_lang:
            st.warning(t("debate.stale_lang_warn"))

if "last_debate" in st.session_state:
    result = st.session_state["last_debate"]
    verdict = result["verdict"]
    reports = result["reports"]

    st.success(
        t(
            "debate.complete",
            n_reports=len(reports),
            n_rec=len(verdict.get("recommended_sectors", [])),
            n_veto=len(verdict.get("vetoed_sectors", [])),
            n_dis=len(verdict.get("disagreements", [])),
        )
    )

    st.markdown(f"### {t('debate.section.verdict')}")
    col1, col2, col3 = st.columns(3)
    col1.success(f"{t('debate.overweight')}: " + (", ".join(verdict.get("recommended_sectors", [])) or "—"))
    col2.error(f"{t('debate.vetoed')}: " + (", ".join(verdict.get("vetoed_sectors", [])) or "—"))
    col3.info(f"{t('debate.disagreements')}: {len(verdict.get('disagreements', []))}")
    st.write(verdict.get("narrative", ""))

    st.markdown(f"### {t('debate.section.reports')}")
    tabs = st.tabs([t("debate.tab.quant"), t("debate.tab.macro"), t("debate.tab.risk")])
    role_order = ["quant", "macro", "risk"]
    for role, tab in zip(role_order, tabs):
        rep = reports.get(role, {})
        with tab:
            if not rep:
                st.info(t("debate.no_report", role=role))
                continue
            st.markdown(f"**{t('debate.summary')}**: {rep.get('summary', '')}")
            if rep.get("caveats"):
                for c in rep["caveats"]:
                    st.caption(f"⚠ {t('debate.caveat')}: {c}")
            votes = rep.get("votes", [])
            if votes:
                df = pd.DataFrame(votes)
                df_show = df[["sector", "stance", "confidence", "rationale"]].copy()
                # Translate the `stance` enum values + column names so the
                # whole table follows the active UI language.
                _STANCE_KEY = {
                    "overweight":  "debate.stance.overweight",
                    "neutral":     "debate.stance.neutral",
                    "underweight": "debate.stance.underweight",
                    "veto":        "debate.stance.veto",
                }
                df_show["stance"] = df_show["stance"].map(
                    lambda s: t(_STANCE_KEY.get(str(s).lower(), "debate.stance.neutral"))
                )
                df_show.rename(
                    columns={
                        "sector":     t("debate.col.sector"),
                        "stance":     t("debate.col.stance"),
                        "confidence": t("debate.col.confidence"),
                        "rationale":  t("debate.col.rationale"),
                    },
                    inplace=True,
                )
                st.dataframe(df_show, use_container_width=True, hide_index=True)
                with st.expander(t("debate.evidences")):
                    for v in votes:
                        if v.get("evidences"):
                            st.markdown(f"**{v['sector']}**")
                            for e in v["evidences"]:
                                st.markdown(
                                    f"- [{e.get('source', '?')}|w={e.get('weight', 0):.2f}] {e.get('content', '')[:160]}"
                                )

    st.markdown(f"### {t('debate.section.dis')}")
    disagreements = verdict.get("disagreements", [])
    if not disagreements:
        st.caption(t("debate.consensus"))
    else:
        rows = [
            {
                t("debate.col.sector"):     d["sector"],
                t("debate.col.pro"):        ", ".join(d.get("agents_pro", [])),
                t("debate.col.con"):        ", ".join(d.get("agents_con", [])),
                t("debate.col.resolution"): d.get("resolution", ""),
            }
            for d in disagreements
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander(t("debate.raw")):
        st.json(result)

else:
    st.info(t("debate.wait"))
