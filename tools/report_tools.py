import json
import os
import re
from langchain_core.tools import tool

from scripts.report_data import build_report_data

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def _stringify_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _load_report_payload(report_data: str, template_type: str) -> dict:
    try:
        payload = json.loads(report_data)
    except json.JSONDecodeError:
        return {"content": report_data}

    if not isinstance(payload, dict):
        return {"content": report_data}

    if template_type == "weekly_report":
        required_keys = {"report_week", "golden_industries", "etf_table"}
        if required_keys.issubset(payload.keys()):
            return payload
        return build_report_data(payload)

    return payload


def _render_template(template: str, payload: dict) -> str:
    placeholders = re.findall(r"\{\{(\w+)\}\}", template)
    rendered = template
    for key in placeholders:
        rendered = rendered.replace("{{" + key + "}}", _stringify_value(payload.get(key)))
    return rendered


def _resolve_template_path(template_type: str, lang: str) -> str:
    """Pick locale-specific template (e.g. weekly_report.en.md) when present;
    otherwise fall back to the default `<type>.md` (Chinese baseline)."""
    lang_norm = (lang or "").lower()
    if lang_norm == "en":
        en_path = os.path.join(TEMPLATE_DIR, f"{template_type}.en.md")
        if os.path.exists(en_path):
            return en_path
    return os.path.join(TEMPLATE_DIR, f"{template_type}.md")


@tool
def generate_report(
    report_data: str,
    template_type: str = "weekly_report",
    role: str = "researcher",
    lang: str = "zh",
) -> str:
    """
    Generate a formatted report using a template.

    Args:
        report_data: Structured data to fill into the report (text/JSON)
        template_type: Template type (weekly_report, talking_points, approval_form)
        role: User role (researcher, rm, compliance) — determines output format
        lang: Output locale ("zh" or "en"). Picks templates/<type>.en.md when "en".
    """
    template_path = _resolve_template_path(template_type, lang)

    if not os.path.exists(template_path):
        return f"Template not found: {template_type}. Available: weekly_report, talking_points, approval_form."

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    payload = _load_report_payload(report_data, template_type)
    rendered = _render_template(template, payload)
    return f"<!-- template={template_type}, role={role}, lang={lang} -->\n{rendered}"
