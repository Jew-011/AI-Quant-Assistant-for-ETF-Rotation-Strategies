"""Shared import bootstrap for Streamlit pages."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

# Fall back to repo-bundled demo credentials when no .env is present, so
# a fresh clone of the repo is runnable with zero configuration.
try:
    from config._demo_keys import apply_demo_keys
    apply_demo_keys()
except Exception:
    pass

PROJECT_ROOT = _ROOT
TRACE_DIR = os.path.join(_ROOT, "traces")
HITL_DIR = os.path.join(_ROOT, "traces", "hitl")
MEMORY_DIR = os.path.join(_ROOT, "traces", "memory")
DOCS_DIR = os.path.join(_ROOT, "docs")

# Ensure session-state language key exists before any page accesses it.
try:
    from frontend.i18n import init_lang  # noqa: E402

    init_lang()
except Exception:
    pass
