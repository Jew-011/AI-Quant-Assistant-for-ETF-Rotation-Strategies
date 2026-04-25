"""
Self-check prompt appended to the Finalizer stage.

Kept as a function so callers can request the locale-appropriate version.
The body is English; the output-language directive is appended via
``with_lang`` to honour the user's UI choice.
"""
from __future__ import annotations

from agent.prompts._lang import with_lang


_REFLECTION_BODY = """Before emitting the final recommendation, run the following self-check on the portfolio:

1. **Concentration risk** — is the offence layer too concentrated (for example three cyclicals)? Is there a defence layer to balance it?
2. **Risk and compliance** — are single-ETF weights within limit? Is the cash buffer hit? Is sector concentration within the red line?
3. **Signal vs news conflict** — does any sector in the Golden Zone face recent negative news (tariffs, policy, overcapacity)? If so, flag the disagreement or downgrade the position.
4. **Veto list** — did you skip any sector that should be vetoed per `get_ic_overlay_config`?
5. **Circuit breakers and warnings** — if the market is highly volatile (for example micro-caps down >10% over 3 days), flag a position cut or a switch to defence.
6. **3-3-2 structure** — is the offence / allocation / defence ratio reasonable? Does the defence layer include low-volatility names (dividend, utilities)?

If you find an issue, adjust the portfolio and explain why. If everything is compliant, confirm the portfolio and save the Decision Trace.
"""


def get_reflection_prompt(output_language: str = "en") -> str:
    """Return the reflection self-check prompt with the active language directive."""
    return with_lang(_REFLECTION_BODY, output_language)


# Backwards-compatible alias — some legacy paths import the bare string.
REFLECTION_PROMPT = _REFLECTION_BODY
