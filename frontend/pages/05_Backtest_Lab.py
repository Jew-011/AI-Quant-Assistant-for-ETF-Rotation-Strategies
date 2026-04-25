"""Page 5 — Backtest Lab."""
from __future__ import annotations

import frontend._bootstrap  # noqa: F401

from datetime import datetime, timedelta

import streamlit as st

from frontend._progress_view import progress_view
from frontend.i18n import current_lang, t
from tools.backtest_tools import run_backtest

st.title(t("bt.title"))
st.caption(t("bt.caption"))

MARKET_LABELS = {
    "a_share": t("common.market.a_share"),
    "hk":      t("common.market.hk"),
    "us":      t("common.market.us"),
}
FREQ_LABELS = {
    "monthly": t("bt.title.monthly"),
    "weekly":  t("bt.title.weekly"),
}

with st.sidebar:
    st.header(t("bt.sidebar.header"))
    market = st.selectbox(
        t("common.market"),
        options=list(MARKET_LABELS.keys()),
        format_func=lambda k: MARKET_LABELS[k],
        index=0,
    )
    today = datetime.now()
    # Roll end_date back to the most recent weekday so we never default to a
    # market-closed Saturday / Sunday (which would break backtest period returns).
    end_anchor = today
    while end_anchor.weekday() >= 5:  # 5=Sat, 6=Sun
        end_anchor -= timedelta(days=1)
    default_start = (end_anchor - timedelta(days=730)).strftime("%Y-%m-%d")
    default_end = end_anchor.strftime("%Y-%m-%d")
    start_date = st.text_input(t("bt.start"), value=default_start)
    end_date = st.text_input(t("bt.end"), value=default_end)
    freqs = st.multiselect(
        t("bt.freqs"),
        options=list(FREQ_LABELS.keys()),
        default=list(FREQ_LABELS.keys()),
        format_func=lambda k: FREQ_LABELS[k],
    )
    run = st.button(t("bt.run"), use_container_width=True, type="primary")

if run:
    import concurrent.futures as _f

    ui_lang = current_lang()
    results: dict[str, str] = {}
    with progress_view() as cb:
        with _f.ThreadPoolExecutor(max_workers=max(len(freqs), 1)) as pool:
            futures = {
                pool.submit(
                    run_backtest.invoke,
                    {
                        "market": market,
                        "start_date": start_date,
                        "end_date": end_date,
                        "rebalance_freq": freq,
                        "lang": ui_lang,
                    },
                ): freq
                for freq in freqs
            }
            for freq in freqs:
                cb("backtest.start",
                   t("progress.bt.start", freq=FREQ_LABELS.get(freq, freq)),
                   "info")
            for fut in _f.as_completed(futures):
                freq = futures[fut]
                try:
                    results[freq] = str(fut.result())
                    cb("backtest.done",
                       t("progress.bt.done", freq=FREQ_LABELS.get(freq, freq)),
                       "success")
                except Exception as exc:
                    results[freq] = f"Error: {exc}"
                    cb("backtest.failed",
                       t("progress.bt.failed", freq=FREQ_LABELS.get(freq, freq), err=str(exc)[:120]),
                       "error")
        cb("backtest.all_done",
           t("progress.bt.all_done", n=len(results)),
           "success")
    st.session_state["backtest_results"] = results
    st.session_state["backtest_results_lang"] = ui_lang

results = st.session_state.get("backtest_results", {})
cached_lang = st.session_state.get("backtest_results_lang")
if results and cached_lang and cached_lang != current_lang():
    st.warning(t("bt.stale_lang_warn"))


def _looks_like_zero_metrics(text: str) -> bool:
    """Heuristic: every numeric metric is 0 / 0.00 / nan -> result is meaningless."""
    import re
    nums = re.findall(r"[-+]?\d+\.\d+|nan", text.lower())
    if not nums:
        return False
    return all(n in {"0.00", "0", "-0.00", "nan"} for n in nums)


if results:
    if any(_looks_like_zero_metrics(out) for out in results.values()):
        st.info(t("bt.zero_metrics_hint"))
    cols = st.columns(len(results))
    for col, (freq, out) in zip(cols, results.items()):
        with col:
            st.markdown(f"### {FREQ_LABELS.get(freq, freq.title())}")
            st.code(out[:6000], language="text")
else:
    st.info(t("bt.wait"))
