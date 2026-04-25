"""
Cheap post-hoc translation of structured agent outputs.

The Multi-Agent Debate is run ONCE in the user's current UI language; this
module then takes the resulting JSON and produces a "mirror" copy whose
free-text fields are translated into the OTHER language. Both copies are
cached on the page so that later UI-language switches become instantaneous
(no need to re-invoke 3 specialists + a coordinator).

Design choices:
- Only free-text PROSE fields are translated. Enum values (`stance`,
  `role`), numeric fields (`confidence`), domain identifiers
  (`sector`, ETF tickers) and the structural shape are preserved verbatim.
- Translation runs as ONE LLM call (not per-field) by batching every text
  segment into a numbered table and parsing the response back. This keeps
  the cost in the cents-per-debate range and the latency below ~5s.
- A dedicated cheap+fast model (`gpt-4o-mini`) is used by default, which
  is independent of the heavyweight specialist models the user picked.
- Failure is silent: if the translation call raises or returns malformed
  JSON, the original (untranslated) result is returned. The Debate page
  will then fall back to its existing "stale language" warning UX.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Iterable

from langchain_openai import ChatOpenAI

# ---------------------------------------------------------------------------
# Field selection
# ---------------------------------------------------------------------------

# Dotted-path patterns of fields to translate. We use a small allowlist so
# adding new structural fields later doesn't accidentally trigger spurious
# translation calls. Each pattern matches the LAST segment of the JSON path.
_TRANSLATABLE_KEYS: frozenset[str] = frozenset(
    {
        "summary",
        "narrative",
        "rationale",
        "content",      # evidences[*].content
        "resolution",   # disagreements[*].resolution
        "caveats",      # list[str]
    }
)

# Hint label per target language used in the system prompt.
_LANG_LABEL = {"en": "English", "zh": "Simplified Chinese (简体中文)"}


# ---------------------------------------------------------------------------
# Walk + collect / inject
# ---------------------------------------------------------------------------


def _collect(obj: Any, out: list[tuple[list, str]], path: list) -> None:
    """Walk `obj` recursively. For every (path, str) hit on a translatable
    key, append (path_list, original_text) to `out`.

    `path` is a list of dict keys / list indices used later by `_inject` to
    write the translated text back into the deep-copied result. Strings
    that are blank or "(none)" are skipped to save tokens.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = path + [k]
            if k in _TRANSLATABLE_KEYS:
                if isinstance(v, str) and v.strip() and v.strip() != "(none)":
                    out.append((new_path, v))
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, str) and item.strip():
                            out.append((new_path + [i], item))
                        else:
                            _collect(item, out, new_path + [i])
                else:
                    _collect(v, out, new_path)
            else:
                _collect(v, out, new_path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _collect(item, out, path + [i])


def _inject(target: Any, path: list, value: str) -> None:
    cur = target
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = value


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


_BATCH_PROMPT = """You are a precise English ↔ Chinese translator for a
financial agent's structured report.

You will receive a JSON list of strings; translate EACH string into
{lang_label}. Keep:
- numbers, percentages, ETF tickers (e.g. 159915.SZ),
- single-token sector names that are commonly written in Chinese
  (电子, 通信, 银行 etc.) when translating INTO Chinese — and translate
  those same tokens to natural English equivalents (Electronics,
  Telecommunications, Banks, ...) when translating INTO English,
- factor names (ma_score, momentum, trend_score) verbatim.
Do not summarise. Do not merge or split items. Output STRICTLY a JSON
list of the same length, in the same order, no commentary.

Input:
{payload}
"""


def _llm_translate_batch(strings: list[str], target_lang: str, model: str) -> list[str]:
    """Send all strings in one shot. Returns translated strings in the same
    order. Raises on any error so the caller can fall back."""
    llm = ChatOpenAI(model=model, temperature=0.1)
    payload = json.dumps(strings, ensure_ascii=False)
    prompt = _BATCH_PROMPT.format(
        lang_label=_LANG_LABEL.get(target_lang, "English"),
        payload=payload,
    )
    raw = llm.invoke([{"role": "user", "content": prompt}]).content
    if isinstance(raw, list):
        # Some models return list[BaseMessage] segments
        raw = "".join(getattr(c, "text", str(c)) for c in raw)
    raw = str(raw).strip()
    # Tolerate Markdown-fenced JSON
    fenced = re.match(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    out = json.loads(raw)
    if not isinstance(out, list) or len(out) != len(strings):
        raise ValueError(
            f"Translator returned {type(out).__name__} of length "
            f"{len(out) if isinstance(out, list) else '?'}, expected {len(strings)}"
        )
    return [str(x) for x in out]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def translate_debate_result(
    result: dict,
    target_lang: str,
    model: str | None = None,
) -> dict:
    """Return a deep-copy of `result` whose free-text fields are translated
    into `target_lang` (`'en'` or `'zh'`). Original on any failure.

    Parameters
    ----------
    result        : dict produced by run_debate_parallel (contains
                    `reports`, `verdict`, `inputs`, optionally `models_used`).
    target_lang   : 'en' or 'zh'.
    model         : LLM id to use for translation. Defaults to gpt-4o-mini —
                    cheap, fast, multilingual, plenty of quality for a JSON
                    rewrite task. Override with env var
                    OPENAI_MODEL_TRANSLATOR if your endpoint doesn't serve it.
    """
    if target_lang not in ("en", "zh"):
        return result
    if not isinstance(result, dict):
        return result

    chosen = model or os.getenv("OPENAI_MODEL_TRANSLATOR", "gpt-4o-mini")

    fields: list[tuple[list, str]] = []
    _collect(result, fields, [])
    if not fields:
        return result

    try:
        translated = _llm_translate_batch(
            [orig for _, orig in fields],
            target_lang=target_lang,
            model=chosen,
        )
    except Exception as exc:
        # Silent fallback — caller decides how to react (keep showing the
        # stale-language warning, retry on next switch, etc.).
        print(f"[translate] translation to {target_lang} failed: {exc}")
        return result

    out = copy.deepcopy(result)
    for (path, _orig), new_text in zip(fields, translated):
        try:
            _inject(out, path, new_text)
        except (KeyError, IndexError, TypeError):
            continue
    out["_lang"] = target_lang
    return out


# ---------------------------------------------------------------------------
# Helper used by frontend: build both languages from a single run
# ---------------------------------------------------------------------------


def make_bilingual_debate(
    result: dict,
    primary_lang: str,
    model: str | None = None,
) -> dict[str, dict]:
    """Given a debate result freshly produced in `primary_lang`, return
    a dict ``{"en": ..., "zh": ...}`` so the page can render either
    language without a re-run.

    The primary copy is stored verbatim; the secondary copy is the
    translated mirror. On translation failure the secondary slot still
    contains the primary copy (better than a missing key)."""
    if primary_lang not in ("en", "zh"):
        primary_lang = "en"
    other = "zh" if primary_lang == "en" else "en"

    primary_copy = copy.deepcopy(result)
    primary_copy["_lang"] = primary_lang

    secondary = translate_debate_result(result, target_lang=other, model=model)
    return {primary_lang: primary_copy, other: secondary}
