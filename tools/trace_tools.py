import os
import json
from datetime import datetime
from langchain_core.tools import tool

TRACE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "traces")
os.makedirs(TRACE_DIR, exist_ok=True)

@tool
def save_decision_trace(trace_json: str) -> str:
    """
    Save a complete Decision Trace as a JSON file (archived by date).
    The trace should include: factor scores, quadrant results, veto details,
    ETF portfolio, risk check results, reasoning chain, config version, timestamps.
    
    Args:
        trace_json: JSON string containing the full decision trace
    """
    try:
        trace = json.loads(trace_json)
    except json.JSONDecodeError:
        return "Error: Invalid JSON in trace_json."

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(TRACE_DIR, date_folder)
    os.makedirs(folder, exist_ok=True)

    filename = f"trace_{timestamp}.json"
    filepath = os.path.join(folder, filename)

    trace["saved_at"] = datetime.now().isoformat()
    trace["approval_status"] = trace.get("approval_status", "pending")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(trace, f, ensure_ascii=False, indent=2)

    return f"Decision Trace saved: {filepath}"

@tool
def get_decision_history(days: int = 7) -> str:
    """
    Retrieve recent Decision Traces.
    
    Args:
        days: Number of recent days to look back
    """
    from datetime import timedelta
    results = []
    for i in range(days):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        folder = os.path.join(TRACE_DIR, date_str)
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            if fname.endswith(".json"):
                filepath = os.path.join(folder, fname)
                with open(filepath, "r", encoding="utf-8") as f:
                    trace = json.load(f)
                summary = {
                    "file": fname,
                    "date": date_str,
                    "saved_at": trace.get("saved_at", "N/A"),
                    "approval_status": trace.get("approval_status", "N/A"),
                }
                results.append(str(summary))

    if not results:
        return f"No Decision Traces found in the past {days} days."
    return "\n".join(results)
