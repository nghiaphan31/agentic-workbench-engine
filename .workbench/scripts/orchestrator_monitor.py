#!/usr/bin/env python3
"""
orchestrator_monitor.py — Orchestrator Agent Status Monitor

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/orchestrator_monitor.py

Comprehensive monitoring script for the Orchestrator Agent.
Reports on:
1. Pending human actions (HITL gates)
2. Dependency blocks
3. Blocking states (RED, REGRESSION_RED, INTEGRATION_RED)

Generates a handoff report written to handoff-state.md.

Usage:
  python orchestrator_monitor.py status           # Full status report
  python orchestrator_monitor.py status --verbose # Detailed output
  python orchestrator_monitor.py gates            # Gate status only
  python orchestrator_monitor.py deps             # Dependency status only
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent scripts dir for imports
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent.parent
STATE_JSON = REPO_ROOT / "state.json"
HOT_CONTEXT = REPO_ROOT / "memory-bank" / "hot-context"
HANDOFF_MD = HOT_CONTEXT / "handoff-state.md"

# Import sibling scripts
import importlib.util
gatekeeper_spec = importlib.util.spec_from_file_location("gatekeeper", SCRIPTS_DIR / "gatekeeper.py")
gatekeeper = importlib.util.module_from_spec(gatekeeper_spec)
gatekeeper_spec.loader.exec_module(gatekeeper)

gate_notification_spec = importlib.util.spec_from_file_location("gate_notification", SCRIPTS_DIR / "gate_notification.py")
gate_notification = importlib.util.module_from_spec(gate_notification_spec)
gate_notification_spec.loader.exec_module(gate_notification)


def load_state() -> dict:
    if not STATE_JSON.exists():
        return {}
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check_blocking_states(state: dict) -> list:
    """Check for blocking states: RED, REGRESSION_RED, INTEGRATION_RED, PIVOT_IN_PROGRESS."""
    blocking = []
    current_state = state.get("state", "")
    active_req_id = state.get("active_req_id")

    blocking_states = {
        "RED": "Implementation failing — Developer Agent needs to fix",
        "REGRESSION_RED": "Regression detected — Developer Agent must fix",
        "INTEGRATION_RED": "Integration tests failing — Developer Agent must fix",
        "PIVOT_IN_PROGRESS": "Pivot in progress — Human approval needed at HITL 1.5",
    }

    if current_state in blocking_states:
        blocking.append({
            "req_id": active_req_id or "unknown",
            "state": current_state,
            "issue": blocking_states[current_state],
            "is_human_blocking": current_state == "PIVOT_IN_PROGRESS",
        })

    return blocking


def check_dependency_blocks(state: dict) -> list:
    """Check for DEPENDENCY_BLOCKED features."""
    blocked = []
    feature_registry = state.get("feature_registry", {})

    for req_id, info in feature_registry.items():
        if info.get("state") == "DEPENDENCY_BLOCKED":
            depends_on = info.get("depends_on", [])
            unmet = [
                dep for dep in depends_on
                if feature_registry.get(dep, {}).get("state") != "MERGED"
            ]
            blocked.append({
                "req_id": req_id,
                "state": "DEPENDENCY_BLOCKED",
                "depends_on": depends_on,
                "unmet": unmet,
                "is_human_blocking": False,  # Orchestrator monitors, not human
            })

    return blocked


def generate_orchestrator_report(state: dict) -> dict:
    """Generate comprehensive orchestrator status report."""
    # Gate notifications
    gate_report = gate_notification.check_gates(state)

    # Dependency blocks
    dep_blocks = check_dependency_blocks(state)

    # Blocking states
    blocking_states = check_blocking_states(state)

    # Enrollment check
    enrollment_result = gatekeeper.check_enrollment(state)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_req_id": state.get("active_req_id"),
        "current_state": state.get("state"),
        "enrollment": {
            "level": enrollment_result.level,
            "message": enrollment_result.message,
            "is_blocking": enrollment_result.level == "CRITICAL",
        },
        "pending_gates": [
            {
                "req_id": g.req_id,
                "gate": g.gate,
                "feature_slug": g.feature_slug,
                "state": g.state,
                "action_required": g.action_required,
                "is_human_blocking": g.gate in ["HITL 1", "HITL 2", "HITL 1.5"],
            }
            for g in gate_report.gates
        ],
        "dependency_blocks": dep_blocks,
        "blocking_states": blocking_states,
        "summary": {
            "total_pending_gates": len(gate_report.gates),
            "human_blocking_gates": len([g for g in gate_report.gates if g.gate in ["HITL 1", "HITL 2", "HITL 1.5"]]),
            "total_dependency_blocks": len(dep_blocks),
            "total_blocking_states": len(blocking_states),
        }
    }


def format_status_table(report: dict, verbose: bool = False) -> str:
    """Format the orchestrator status report as a markdown table."""
    lines = []

    # Summary header
    summary = report["summary"]
    lines.append(f"## Orchestrator Status Report — {report['timestamp']}")
    lines.append("")

    # Enrollment status
    enrollment = report["enrollment"]
    if enrollment["level"] == "CRITICAL":
        lines.append(f"🚨 **ENROLLMENT BLOCKING:** {enrollment['message']}")
        lines.append("")
    elif enrollment["level"] == "WARNING":
        lines.append(f"⚠️ **ENROLLMENT WARNING:** {enrollment['message']}")
        lines.append("")

    # Summary counts
    lines.append("### Summary")
    lines.append(f"- Pending Gates: {summary['total_pending_gates']} ({summary['human_blocking_gates']} human-blocking)")
    lines.append(f"- Dependency Blocks: {summary['total_dependency_blocks']}")
    lines.append(f"- Blocking States: {summary['total_blocking_states']}")
    lines.append("")

    # Pending human actions
    pending_gates = report["pending_gates"]
    if pending_gates:
        lines.append("### ⚠️ Pending Human Actions")
        lines.append("")
        lines.append("| REQ-ID | Gate | Feature | Action Required |")
        lines.append("|--------|------|---------|----------------|")
        for g in pending_gates:
            lines.append(f"| {g['req_id']} | {g['gate']} | {g['feature_slug']} | {g['action_required']} |")
        lines.append("")
    else:
        lines.append("### ✅ No Pending Human Actions")
        lines.append("")

    # Dependency blocks
    dep_blocks = report["dependency_blocks"]
    if dep_blocks:
        lines.append("### Dependency Blocks (Orchestrator Monitoring)")
        lines.append("")
        lines.append("| REQ-ID | Blocked By | Status |")
        lines.append("|--------|-----------|--------|")
        for d in dep_blocks:
            unmet_str = ", ".join(d["unmet"]) if d["unmet"] else "none"
            lines.append(f"| {d['req_id']} | {', '.join(d['depends_on'])} | Unmet: {unmet_str} |")
        lines.append("")
    else:
        lines.append("### ✅ No Dependency Blocks")
        lines.append("")

    # Blocking states
    blocking = report["blocking_states"]
    if blocking:
        lines.append("### 🔴 Blocking States")
        lines.append("")
        lines.append("| REQ-ID | State | Issue |")
        lines.append("|--------|-------|-------|")
        for b in blocking:
            lines.append(f"| {b['req_id']} | {b['state']} | {b['issue']} |")
        lines.append("")

    return "\n".join(lines)


def write_handoff_report(report: dict):
    """Write orchestrator status report to handoff-state.md."""
    if not HANDOFF_MD.exists():
        content = "# handoff-state.md — Inter-Agent Handoff Message Bus\n\n"
    else:
        content = HANDOFF_MD.read_text(encoding="utf-8")

    # Check if already has orchestrator report
    marker = "<!-- ORCHESTRATOR STATUS REPORT -->"
    if marker in content:
        # Replace existing report
        lines = content.split("\n")
        new_lines = []
        skip_until_next_marker = False
        for line in lines:
            if marker in line:
                skip_until_next_marker = True
                continue
            elif skip_until_next_marker and line.startswith("## Orchestrator Status Report"):
                # Found next section, stop skipping
                skip_until_next_marker = False
                new_lines.append(line)
            elif skip_until_next_marker:
                continue
            else:
                new_lines.append(line)
        content = "\n".join(new_lines)

    formatted = format_status_table(report)
    entry = f"\n{marker}\n{formatted}\n"

    HANDOFF_MD.write_text(content + entry, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Orchestrator Agent Status Monitor")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status command — full orchestrator report
    status_parser = subparsers.add_parser("status", help="Full orchestrator status report")
    status_parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    status_parser.add_argument("--write-handoff", action="store_true", help="Write to handoff-state.md")

    # gates command — gate status only
    subparsers.add_parser("gates", help="Pending gates only")

    # deps command — dependency status only
    subparsers.add_parser("deps", help="Dependency blocks only")

    args = parser.parse_args()

    state = load_state()
    report = generate_orchestrator_report(state)

    if args.command == "status":
        print(format_status_table(report, verbose=args.verbose))
        if getattr(args, "write_handoff", False):
            write_handoff_report(report)
            print("\n[GATE NOTIFICATION] Updated handoff-state.md")

    elif args.command == "gates":
        # Just gates summary
        gates = report["pending_gates"]
        if gates:
            print(f"[ORCHESTRATOR] {len(gates)} pending gate(s)")
            for g in gates:
                human_marker = "⚠️ HUMAN BLOCKING" if g["is_human_blocking"] else "Orchestrator"
                print(f"  {g['req_id']} @ {g['gate']} ({human_marker})")
        else:
            print("[ORCHESTRATOR] No pending gates")

    elif args.command == "deps":
        # Just dependency summary
        deps = report["dependency_blocks"]
        if deps:
            print(f"[ORCHESTRATOR] {len(deps)} dependency block(s)")
            for d in deps:
                print(f"  {d['req_id']} blocked by {', '.join(d['depends_on'])}")
        else:
            print("[ORCHESTRATOR] No dependency blocks")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()