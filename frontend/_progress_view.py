"""
Streamlit ``st.status`` wrapper that displays live progress events from the
backend ``ProgressEmitter`` channel.

Typical usage:

    from frontend._progress_view import progress_view
    from agent.graph import run_agent

    with progress_view() as cb:
        result = run_agent(prompt, ..., progress_cb=cb)

Behaviour:
    * The status box header always shows the most recent label.
    * Inside the box we render the last ~40 events as a tailing log so the
      user can see exactly what the backend is doing right now.
    * On normal exit the box is collapsed and marked "complete"; on
      exception it stays expanded and is marked "error".
    * The callback signature matches ``ProgressCallback``:
      ``cb(phase, label, level)``.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Iterator

import streamlit as st

from frontend.i18n import t


_LEVEL_GLYPH = {
    "info":    "•",
    "success": "✓",
    "warn":    "!",
    "error":   "x",
}


@contextmanager
def progress_view(
    initial_label: str | None = None,
    *,
    expanded: bool = False,
    max_lines: int = 40,
) -> Iterator[Callable[[str, str, str], None]]:
    """Context manager yielding a backend-friendly progress callback.

    Parameters
    ----------
    initial_label
        Header shown before the first backend event arrives. Falls back to
        the localised default ("Working — click to view live activity").
    expanded
        Whether the inner activity log starts open. Defaults to False so the
        UI stays compact for casual users; debug-minded users can click open.
    max_lines
        How many tail log lines to keep on screen. Older lines roll off.
    """
    label = initial_label or t("progress.box.label")
    events: list[str] = []

    with st.status(label, expanded=expanded, state="running") as box:
        log_slot = st.empty()

        def _render_log() -> None:
            if not events:
                log_slot.markdown("_…_")
                return
            log_slot.markdown("\n\n".join(events[-max_lines:]))

        def cb(phase: str, msg: str, level: str = "info") -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            glyph = _LEVEL_GLYPH.get(level, "•")
            events.append(f"`{ts}` {glyph} **{phase}** — {msg}")
            try:
                box.update(label=msg)
                _render_log()
            except Exception:
                # Streamlit can raise from a background thread; ignore so
                # backend execution is never interrupted by UI hiccups.
                pass

        try:
            yield cb
        except Exception as exc:
            cb("failed", t("progress.box.failed") + f": {exc}", level="error")
            box.update(label=t("progress.box.failed"), state="error", expanded=True)
            raise
        else:
            box.update(label=t("progress.box.done"), state="complete", expanded=False)


__all__ = ["progress_view"]
