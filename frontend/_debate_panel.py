"""
Live Multi-Agent Debate panel.

Renders 3 specialist cards (Quant / Macro / Risk) side-by-side that visually
reflect the parallel debate in real-time. Cards transition through:

    idle (gray)  →  thinking (yellow, animated) → done (green) → result (colored by stance)

Usage in a Streamlit page:

    board = DebateCardBoard(roles=("quant", "macro", "risk"))
    board.render_initial()

    # Forward progress events from run_debate_parallel into the board
    cb = chain_callbacks(board.as_progress_callback(), progress_view_cb)
    result = run_debate_parallel(inputs, progress_cb=cb)

    # Once finished, fill in stances + top sectors
    board.render_results(result["reports"])
"""
from __future__ import annotations

from typing import Callable, Iterable

import streamlit as st

from frontend.i18n import t

# Static metadata for each role: emoji, i18n key for name, i18n key for blurb,
# and a CSS color used in the "result" view.
_ROLE_META: dict[str, dict[str, str]] = {
    "quant": {
        "icon": "📊",
        "name_key":  "debate.role.quant.name",
        "blurb_key": "debate.role.quant.blurb",
    },
    "macro": {
        "icon": "🌍",
        "name_key":  "debate.role.macro.name",
        "blurb_key": "debate.role.macro.blurb",
    },
    "risk": {
        "icon": "🛡️",
        "name_key":  "debate.role.risk.name",
        "blurb_key": "debate.role.risk.blurb",
    },
}

# Per-stance card border / accent color for the final result view.
_STANCE_COLOR: dict[str, str] = {
    "overweight":  "#16a34a",   # green
    "neutral":     "#64748b",   # slate
    "underweight": "#f59e0b",   # amber
    "veto":        "#dc2626",   # red
}


_PULSE_STYLE_INJECTED = False


def _inject_pulse_keyframes() -> None:
    """Inject the @keyframes once per session (prevents duplicate <style> tags
    from breaking Streamlit's markdown renderer)."""
    global _PULSE_STYLE_INJECTED
    if _PULSE_STYLE_INJECTED:
        return
    st.markdown(
        "<style>"
        "@keyframes dpulse{"
        "0%{box-shadow:0 0 0 0 rgba(250,204,21,0.55);}"
        "70%{box-shadow:0 0 0 12px rgba(250,204,21,0);}"
        "100%{box-shadow:0 0 0 0 rgba(250,204,21,0);}"
        "}"
        ".debate-card{border-radius:10px;padding:14px 16px;"
        "background:rgba(15,23,42,0.55);min-height:140px;}"
        ".debate-card .dc-title{font-size:12.5px;color:#cbd5e1;"
        "letter-spacing:0.06em;text-transform:uppercase;}"
        ".debate-card .dc-status{font-size:18px;margin-top:6px;"
        "color:#f1f5f9;font-weight:600;}"
        ".debate-card .dc-body{font-size:12.5px;color:#94a3b8;"
        "margin-top:8px;line-height:1.5;}"
        "</style>",
        unsafe_allow_html=True,
    )
    _PULSE_STYLE_INJECTED = True


def _card_html(
    *,
    icon: str,
    title: str,
    status_emoji: str,
    status_text: str,
    body_text: str = "",
    accent: str = "#334155",
    pulse: bool = False,
) -> str:
    """Render a single debate card as a SINGLE-LINE HTML string.

    Streamlit's markdown engine treats indented multi-line blocks as code, so
    we keep the entire card on one line (no leading whitespace per line) to
    guarantee it renders as HTML, not as a code block."""
    extra = (
        f"animation:dpulse 1.2s ease-in-out infinite;"
        if pulse
        else ""
    )
    style = (
        f"border:1px solid {accent};border-left:5px solid {accent};{extra}"
    )
    return (
        f'<div class="debate-card" style="{style}">'
        f'<div class="dc-title">{icon}&nbsp;&nbsp;{title}</div>'
        f'<div class="dc-status">{status_emoji} {status_text}</div>'
        f'<div class="dc-body">{body_text}</div>'
        f'</div>'
    )


class DebateCardBoard:
    """Side-by-side live cards for the 3 debate specialists."""

    def __init__(
        self,
        roles: Iterable[str] = ("quant", "macro", "risk"),
        *,
        role_models: dict[str, str] | None = None,
    ):
        self.roles = list(roles)
        self._placeholders: dict[str, "st.delta_generator.DeltaGenerator"] = {}
        # Track each role's current state so re-emits are idempotent.
        self._state: dict[str, str] = {r: "idle" for r in self.roles}
        # Per-role model id, shown as a small badge under the role name so the
        # heterogeneous-ensemble nature of the debate is visible.
        self._role_models: dict[str, str] = role_models or {}

    # ------------------------------------------------------------------ render

    def render_initial(self, *, container: "st.delta_generator.DeltaGenerator | None" = None) -> None:
        """Draw the 3 cards in their idle (Standing by) state."""
        _inject_pulse_keyframes()
        host = container if container is not None else st
        cols = host.columns(len(self.roles), gap="small")
        for col, role in zip(cols, self.roles):
            with col:
                self._placeholders[role] = st.empty()
                self._render_card(role, state="idle")

    def _render_card(
        self,
        role: str,
        *,
        state: str,
        result: dict | None = None,
    ) -> None:
        meta = _ROLE_META[role]
        title = t(meta["name_key"])
        blurb = t(meta["blurb_key"])
        model_id = self._role_models.get(role, "")
        # Add a tiny model badge to the title so the user can SEE which LLM
        # this card is calling — that's what makes the heterogeneous ensemble
        # visually obvious at a glance.
        if model_id:
            title = (
                f"{title} "
                f'<span style="font-size:10.5px;color:#0ea5e9;'
                f'background:rgba(14,165,233,0.12);padding:1px 6px;'
                f'border-radius:6px;margin-left:4px;'
                f'letter-spacing:0;text-transform:none;">'
                f"{model_id}</span>"
            )

        if state == "idle":
            html = _card_html(
                icon=meta["icon"],
                title=title,
                status_emoji="⏸",
                status_text=t("debate.card.standby"),
                body_text=blurb,
                accent="#334155",
            )
        elif state == "thinking":
            html = _card_html(
                icon=meta["icon"],
                title=title,
                status_emoji="💭",
                status_text=t("debate.card.thinking"),
                body_text=blurb,
                accent="#facc15",
                pulse=True,
            )
        elif state == "done":
            html = _card_html(
                icon=meta["icon"],
                title=title,
                status_emoji="✅",
                status_text=t("debate.card.done"),
                body_text=blurb,
                accent="#16a34a",
            )
        elif state == "result" and result is not None:
            stance_raw = (result.get("stance") or "").lower()
            stance_label = t(
                {
                    "overweight":  "debate.stance.overweight",
                    "neutral":     "debate.stance.neutral",
                    "underweight": "debate.stance.underweight",
                    "veto":        "debate.stance.veto",
                }.get(stance_raw, "debate.stance.neutral")
            )
            top_sectors = result.get("top_sectors") or []
            top_str = (
                ", ".join(top_sectors[:3])
                if top_sectors
                else t("debate.card.no_top")
            )
            confidence = result.get("avg_confidence")
            conf_str = (
                f" · {t('debate.card.conf')} {confidence:.0%}"
                if isinstance(confidence, (float, int))
                else ""
            )
            accent = _STANCE_COLOR.get(stance_raw, "#64748b")
            html = _card_html(
                icon=meta["icon"],
                title=title,
                status_emoji="🗳",
                status_text=f"{stance_label}{conf_str}",
                body_text=f"<b>{t('debate.card.top')}:</b> {top_str}",
                accent=accent,
            )
        else:
            return  # unknown state — skip silently

        self._placeholders[role].markdown(html, unsafe_allow_html=True)
        self._state[role] = state

    # -------------------------------------------------------------- callbacks

    def as_progress_callback(self) -> Callable[[str, str, str], None]:
        """Return a sink compatible with ``run_debate_parallel(progress_cb=...)``.

        The sink is called with ``(phase, label, level)``. We only care about
        the phase to drive card transitions, but we keep the signature
        compatible with the generic ``ProgressCallback`` type.
        """

        def _cb(phase: str, _label: str, _level: str) -> None:
            try:
                if phase == "debate.specialists":
                    # All 3 specialists started → flip every idle card to thinking.
                    for r in self.roles:
                        if self._state.get(r) == "idle":
                            self._render_card(r, state="thinking")
                elif phase == "debate.specialist_done":
                    # The role suffix isn't in `phase`; multi_agent.py emits a
                    # localised label such as "{role} agent finished" / "{role} 智能体完成".
                    # We detect the role from the localised label string.
                    for r in self.roles:
                        if r in (_label or "").lower():
                            self._render_card(r, state="done")
                            return
                elif phase == "debate.coordinator":
                    # Belt & braces: anything still "thinking" is now done.
                    for r in self.roles:
                        if self._state.get(r) == "thinking":
                            self._render_card(r, state="done")
            except Exception:
                # Never let the UI break the backend.
                pass

        return _cb

    # ---------------------------------------------------------------- results

    def render_results(self, reports: dict[str, dict]) -> None:
        """After the debate has finished, replace each card with a stance summary
        derived from that specialist's report (the structured ``AgentReport``)."""
        for role in self.roles:
            rep = reports.get(role) or {}
            self._render_card(role, state="result", result=_summarise_report(rep))


# ---------------------------------------------------------------- helpers


def _summarise_report(rep: dict) -> dict:
    """Boil an AgentReport down to (stance, top_sectors, avg_confidence) for the card."""
    votes = rep.get("votes") or []
    if not votes:
        return {"stance": "neutral", "top_sectors": [], "avg_confidence": None}

    stance_score = {"overweight": 1, "neutral": 0, "underweight": -1, "veto": -2}
    weighted = 0.0
    total_w = 0.0
    overweights: list[tuple[str, float]] = []
    for v in votes:
        s = (str(v.get("stance") or "")).lower()
        c = float(v.get("confidence") or 0.0)
        weighted += stance_score.get(s, 0) * c
        total_w += c
        if s == "overweight":
            overweights.append((v.get("sector", "?"), c))

    avg = weighted / total_w if total_w else 0.0
    if avg >= 0.4:
        stance = "overweight"
    elif avg <= -0.6:
        stance = "underweight"
    elif avg <= -1.0:
        stance = "veto"
    else:
        stance = "neutral"

    overweights.sort(key=lambda x: -x[1])
    top_sectors = [name for name, _ in overweights[:3]]

    confidences = [float(v.get("confidence") or 0.0) for v in votes]
    avg_conf = sum(confidences) / len(confidences) if confidences else None

    return {"stance": stance, "top_sectors": top_sectors, "avg_confidence": avg_conf}


__all__ = ["DebateCardBoard"]
