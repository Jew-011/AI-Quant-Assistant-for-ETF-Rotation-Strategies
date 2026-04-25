import os
import yaml
from langchain_core.tools import tool

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")

@tool
def get_ic_overlay_config(market: str = "a_share") -> str:
    """
    Get current IC Overlay configuration: subjective observation pools and veto list.
    Returns the pools and active veto rules as text.

    Args:
        market: Market identifier (a_share, hk, us)
    """
    pool_path = os.path.join(CONFIG_DIR, "subjective_pool.yaml")
    veto_path = os.path.join(CONFIG_DIR, "veto_list.yaml")

    with open(pool_path, "r", encoding="utf-8") as f:
        pool_cfg = yaml.safe_load(f)
    with open(veto_path, "r", encoding="utf-8") as f:
        veto_cfg = yaml.safe_load(f)

    lines = [f"=== Observation Pools (version: {pool_cfg.get('version', 'N/A')}) ==="]
    for key, pool in pool_cfg.get("pools", {}).items():
        lines.append(f"\n[{pool['name']}]")
        lines.append(f"  Rationale: {pool['rationale']}")
        lines.append(f"  Industries: {', '.join(pool['industries'])}")

    lines.append(f"\n=== Veto List (version: {veto_cfg.get('version', 'N/A')}) ===")
    for rule in veto_cfg.get("rules", []):
        status = "ACTIVE" if rule.get("active", False) else "INACTIVE"
        lines.append(f"\n[{rule['id']}] {rule['name']} ({status})")
        lines.append(f"  Description: {rule['description']}")
        lines.append(f"  Industries: {', '.join(rule.get('industries', []))}")
        if rule.get("note"):
            lines.append(f"  Note: {rule['note']}")

    return "\n".join(lines)
