"""
Model registry + Streamlit model picker.

Reads ``config/models.yaml`` and exposes:
    - ``load_models()``      -> list[ModelMeta]
    - ``init_model()``       -> seed st.session_state['model'] once
    - ``current_model()``    -> active model id (str)
    - ``current_model_meta()`` -> active ModelMeta (or None)
    - ``model_switcher()``   -> renders a sidebar selectbox + caption

The picked id is also pushed back into ``os.environ['OPENAI_MODEL']`` so any
backend code path that still falls back to the env var (e.g. tools that build
their own LLM client) honours the user's choice.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import streamlit as st

from frontend.i18n import current_lang, t

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "models.yaml",
)


@dataclass(frozen=True)
class ModelMeta:
    id: str
    label: str
    provider: str
    blurb_en: str
    blurb_zh: str
    price_in: float   # USD per 1K input tokens
    price_out: float  # USD per 1K output tokens

    def blurb(self, lang: str) -> str:
        return self.blurb_zh if lang == "zh" else self.blurb_en


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_raw() -> dict:
    try:
        import yaml  # local import: yaml is already in requirements
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def load_models() -> list[ModelMeta]:
    raw = _load_raw()
    items = raw.get("models") or []
    out: list[ModelMeta] = []
    for it in items:
        try:
            out.append(
                ModelMeta(
                    id=str(it["id"]),
                    label=str(it.get("label", it["id"])),
                    provider=str(it.get("provider", "")),
                    blurb_en=str(it.get("blurb_en", "")),
                    blurb_zh=str(it.get("blurb_zh", it.get("blurb_en", ""))),
                    price_in=float(it.get("price_in", 0.0005)),
                    price_out=float(it.get("price_out", 0.002)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def default_model_id() -> str:
    raw = _load_raw()
    fallback = os.getenv("OPENAI_MODEL", "deepseek-v3.2")
    return str(raw.get("default") or fallback)


# ---------------------------------------------------------------------------
# Specialist (per-role) model assignment — heterogeneous multi-agent ensemble.
# ---------------------------------------------------------------------------

SPECIALIST_ROLES: tuple[str, ...] = ("quant", "macro", "risk", "coordinator")


def default_specialist_models() -> dict[str, str]:
    """Read per-role default model ids from ``models.yaml``.

    Returns a dict like ``{"quant": "deepseek-v3.2", "macro": "qwen3-max", ...}``.
    Any role missing from the YAML falls back to ``default_model_id()``.
    """
    raw = _load_raw()
    cfg = raw.get("specialist_models") or {}
    fallback = default_model_id()
    return {role: str(cfg.get(role) or fallback) for role in SPECIALIST_ROLES}


def init_specialist_models() -> None:
    """Seed ``st.session_state['specialist_models']`` once per session."""
    if "specialist_models" not in st.session_state:
        st.session_state["specialist_models"] = default_specialist_models()
    # Sync env vars so the backend (subgraph.py) picks them up.
    sync_specialist_models_to_env()


def current_specialist_models() -> dict[str, str]:
    init_specialist_models()
    return dict(st.session_state["specialist_models"])


def set_specialist_model(role: str, model_id: str) -> None:
    init_specialist_models()
    st.session_state["specialist_models"][role] = model_id
    sync_specialist_models_to_env()


def sync_specialist_models_to_env() -> None:
    """Push the current per-role assignment into env vars.

    Backend code (e.g. ``agent/subgraph.py``) reads these env vars when
    spawning the multi-agent debate, so the picker on the Settings page
    propagates without any additional plumbing.
    """
    cfg = st.session_state.get("specialist_models") or {}
    for role in SPECIALIST_ROLES:
        val = cfg.get(role)
        if val:
            os.environ[f"OPENAI_MODEL_{role.upper()}"] = val


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

def init_model() -> None:
    """Seed ``st.session_state['model']`` once per session."""
    if "model" not in st.session_state:
        st.session_state["model"] = default_model_id()
    # Make sure the env var is in sync — backend tools that build their own
    # ChatOpenAI by reading ``os.environ`` will then pick the same model.
    os.environ["OPENAI_MODEL"] = st.session_state["model"]


def current_model() -> str:
    return st.session_state.get("model") or default_model_id()


def current_model_meta() -> Optional[ModelMeta]:
    cur = current_model()
    for m in load_models():
        if m.id == cur:
            return m
    return None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def model_switcher(location: str = "sidebar") -> str:
    """Render a model dropdown + a one-line description below it.

    Returns the active model id.
    """
    init_model()
    models = load_models()
    if not models:
        # No registry -> fall back to a plain text input so the page still works.
        container = st.sidebar if location == "sidebar" else st
        new_id = container.text_input(
            t("model.label"),
            value=current_model(),
            key="_model_textinput",
        )
        if new_id != current_model():
            st.session_state["model"] = new_id
            os.environ["OPENAI_MODEL"] = new_id
            st.rerun()
        return new_id

    container = st.sidebar if location == "sidebar" else st
    ids = [m.id for m in models]
    cur = current_model()
    if cur not in ids:
        cur = ids[0]
    label_for = {m.id: f"{m.label}  ·  {m.provider}" for m in models}

    new_id = container.selectbox(
        t("model.label"),
        options=ids,
        index=ids.index(cur),
        format_func=lambda i: label_for.get(i, i),
        key="_model_selectbox",
        help=t("model.help"),
    )

    meta = next((m for m in models if m.id == new_id), models[0])
    container.caption(meta.blurb(current_lang()))
    container.caption(
        t(
            "model.price",
            pin=f"{meta.price_in*1000:.2f}",
            pout=f"{meta.price_out*1000:.2f}",
        )
    )

    if new_id != st.session_state.get("model"):
        st.session_state["model"] = new_id
        os.environ["OPENAI_MODEL"] = new_id
        st.rerun()

    os.environ["OPENAI_MODEL"] = new_id
    return new_id
