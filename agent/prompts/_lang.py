"""
Central output-language instruction helper.

Every prompt builder in ``agent.prompts`` is written in English. At the moment
the prompt is sent to the LLM, the builder appends the locale-specific
"output language" instruction returned by ``output_language_instruction(lang)``.
This way:
  * source files stay 100% English (easy to review / grade in English),
  * runtime output language follows the UI language picked by the user.

Sector names and other domain-specific Chinese identifiers are kept verbatim
because they are codes, not prose.
"""
from __future__ import annotations


_INSTRUCTIONS = {
    "en": (
        "## OUTPUT LANGUAGE — STRICT\n"
        "Write the ENTIRE response in clear, professional ENGLISH. "
        "Do NOT switch to Chinese mid-sentence. Sector names, ETF tickers, "
        "and other Chinese-coded identifiers (e.g. `电子`, `159915.SZ`) MAY "
        "stay in their original form because they are domain codes, not prose."
    ),
    "zh": (
        "## 输出语言 — 强制要求\n"
        "请全程使用**简体中文**撰写回复，不要中途切换为英文。"
        "行业名、ETF 代码等领域专有标识（如 `电子`、`159915.SZ`）"
        "保留原始形式即可，无需翻译。"
    ),
}


def normalise_lang(lang: str | None) -> str:
    """Coerce arbitrary input to one of the supported codes (``en`` / ``zh``)."""
    if lang in ("en", "zh"):
        return lang
    return "en"


def output_language_instruction(lang: str | None) -> str:
    """Return the language directive to append to a system prompt."""
    return _INSTRUCTIONS[normalise_lang(lang)]


def with_lang(prompt: str, lang: str | None) -> str:
    """Bracket *prompt* with the language directive so the LLM cannot miss it.

    Short language hints buried at the end of long English prompts are
    routinely ignored by chat models — we therefore inject the directive
    BOTH at the top and bottom of the prompt.
    """
    instr = output_language_instruction(lang)
    return f"{instr}\n\n---\n\n{prompt}\n\n---\n\n{instr}"
