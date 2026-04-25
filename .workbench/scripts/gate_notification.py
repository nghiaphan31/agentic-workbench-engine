#!/usr/bin/env python3
"""
gate_notification.py — Proactive HITL Gate Notification

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/gate_notification.py

Monitors state.json for gate-blocking states and surfaces pending human
actions to the human. This ensures the human knows when they're blocking
the workflow at a HITL gate.

Run during:
- SCAN step (SLC-1 step 0) of startup protocol
- Post-commit hook (optional)
- On-demand via: python gate_notification.py check-gates --verbose

State-to-Gate mapping:
| State | Gate | Human Action |
|-------|------|--------------|
| REQUIREMENTS_LOCKED | HITL 1 | Product Owner must approve .feature files |
| REVIEW_PENDING | HITL 2 | Lead Engineer must approve PR merge |
| DEPENDENCY_BLOCKED | Orchestrator | Only Orchestrator monitors (human not blocking) |
| PIVOT_IN_PROGRESS | HITL 1.5 | Human must approve pivot Git diff |

Usage:
  python gate_notification.py check-gates          # Check pending gates
  python gate_notification.py check-gates --verbose # Human-readable output
  python gate_notification.py update-memory         # Update activeContext.md + handoff-state.md
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
STATE_JSON = REPO_ROOT / "state.json"
HOT_CONTEXT = REPO_ROOT / "memory-bank" / "hot-context"
ACTIVECONTEXT_MD = HOT_CONTEXT / "activeContext.md"
HANDOFF_MD = HOT_CONTEXT / "handoff-state.md"


@dataclass
class GateInfo:
    req_id: str
    gate: str
    feature_slug: str
    state: str
    blocking_since: Optional[str] = None
    action_required: str = ""


@dataclass
class GateReport:
    gates: list = field(default_factory=list)

    def has_pending_gates(self) -> bool:
        return len(self.gates) > 0

    def get_summary(self) -> dict:
        return {
            "total_pending": len(self.gates),
            "hitl_1_pending": len([g for g in self.gates if g.gate == "HITL 1"]),
            "hitl_1_5_pending": len([g for g in self.gates if g.gate == "HITL 1.5"]),
            "hitl_2_pending": len([g for g in self.gates if g.gate == "HITL 2"]),
            "dependency_blocked": len([g for g in self.gates if g.gate == "DEPENDENCY_BLOCKED"]),
        }


# States that indicate a HITL gate is pending human action
GATE_STATES = {
    "REQUIREMENTS_LOCKED": {
        "gate": "HITL 1",
        "action": "Product Owner must approve .feature requirements",
    },
    "REVIEW_PENDING": {
        "gate": "HITL 2",
        "action": "Lead Engineer must approve PR merge to develop",
    },
    "PIVOT_IN_PROGRESS": {
        "gate": "HITL 1.5",
        "action": "Human must approve Git diff on pivot branch",
    },
    "DEPENDENCY_BLOCKED": {
        "gate": "DEPENDENCY_BLOCKED",
        "action": "Orchestrator monitoring — dependencies not yet MERGED",
    },
}


def load_state() -> dict:
    """Load state.json, return empty dict if missing."""
    if not STATE_JSON.exists():
        return {}
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check_gates(state: dict) -> GateReport:
    """
    Scan state.json for gate-blocking states.

    Returns:
        GateReport with list of pending gates
    """
    report = GateReport()
    active_req_id = state.get("active_req_id")
    feature_registry = state.get("feature_registry", {})
    current_state = state.get("state", "")

    # Check if current state is a gate-blocking state
    if current_state in GATE_STATES:
        gate_config = GATE_STATES[current_state]

        # Extract feature slug from active_req_id
        feature_slug = ""
        if active_req_id and active_req_id in feature_registry:
            feature_slug = feature_registry[active_req_id].get("slug", active_req_id)

        report.gates.append(GateInfo(
            req_id=active_req_id or "unknown",
            gate=gate_config["gate"],
            feature_slug=feature_slug,
            state=current_state,
            action_required=gate_config["action"],
        ))

    # Also check feature_registry for any features in gate states
    # (in case the active_req_id doesn't match but other features are waiting)
    for req_id, feature_data in feature_registry.items():
        feat_state = feature_data.get("state", "")
        if feat_state in GATE_STATES and req_id != active_req_id:
            # Skip if already added (active_req_id case above)
            if feat_state == current_state and req_id == active_req_id:
                continue

            gate_config = GATE_STATES[feat_state]
            report.gates.append(GateInfo(
                req_id=req_id,
                gate=gate_config["gate"],
                feature_slug=feature_data.get("slug", req_id),
                state=feat_state,
                action_required=gate_config["action"],
            ))

    return report


def format_gates_table(gates: list) -> str:
    """Format gates as a markdown table."""
    if not gates:
        return "| REQ-ID | Gate | Feature | Action Required |\n|--------|------|---------|----------------|\n| _(empty)_ | — | No pending gates | — |"

    lines = [
        "| REQ-ID | Gate | Feature | Action Required |",
        "|--------|------|---------|----------------|"
    ]
    for g in gates:
        lines.append(f"| {g.req_id} | {g.gate} | {g.feature_slug} | {g.action_required} |")
    return "\n".join(lines)


def update_memory_bank(report: GateReport) -> bool:
    """
    Update activeContext.md and handoff-state.md with pending gates.

    Returns True if updated, False if no changes needed.
    """
    if not HOT_CONTEXT.exists():
        return False

    summary = report.get_summary()
    gates_table = format_gates_table(report.gates)

    # Update activeContext.md — replace the pending actions table
    if ACTIVECONTEXT_MD.exists():
        try:
            content = ACTIVECONTEXT_MD.read_text(encoding="utf-8")
            # Find the Pending Human Actions section and replace table
            if "## ⚠️ Pending Human Actions" in content:
                lines = content.split("\n")
                new_lines = []
                in_table = False
                skip_rest = False

                for i, line in enumerate(lines):
                    if "## ⚠️ Pending Human Actions" in line:
                        new_lines.append(line)
                        # Next line is the table header — replace entirely
                        continue
                    elif line.startswith("| ") and "| REQ-ID |" in line:
                        # Found table header, skip to next non-table line
                        in_table = True
                        new_lines.append(gates_table)
                        continue
                    elif in_table and line.startswith("|"):
                        # Skip table rows
                        continue
                    elif in_table and not line.startswith("|"):
                        # End of table
                        in_table = False
                        new_lines.append(line)
                        continue
                    else:
                        new_lines.append(line)

                new_content = "\n".join(new_lines)
                ACTIVECONTEXT_MD.write_text(new_content, encoding="utf-8")
        except Exception:
            pass  # Best-effort update

    # Update handoff-state.md — append to pending handoffs
    if HANDOFF_MD.exists():
        try:
            content = HANDOFF_MD.read_text(encoding="utf-8")
            if report.has_pending_gates():
                # Find "## Active Handoffs" section
                if "## Active Handoffs" in content:
                    # Check if there's already a pending gates entry
                    if "<!-- Auto-populated by gate_notification" not in content:
                        append_section = f"""
<!-- Auto-populated by gate_notification.py on {datetime.now(timezone.utc).isoformat()} -->
## ⚠️ Pending Human Actions

{gates_table}

"""
                        content += append_section
                        HANDOFF_MD.write_text(content, encoding="utf-8")
        except Exception:
            pass  # Best-effort update

    return True


def main():
    parser = argparse.ArgumentParser(description="HITL Gate Notification")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Human-readable output"
    )
    parser.add_argument(
        "--update-memory", "-u", action="store_true",
        help="Update activeContext.md and handoff-state.md with pending gates"
    )
    args = parser.parse_args()

    state = load_state()
    report = check_gates(state)

    if args.verbose or True:  # Always verbose for now
        summary = report.get_summary()
        print(f"[GATE NOTIFICATION] {summary['total_pending']} pending gate(s) detected")
        print()

        if report.has_pending_gates():
            print("## ⚠️ Pending Human Actions")
            print()
            print(format_gates_table(report.gates))
            print()

            for g in report.gates:
                if g.gate in ["HITL 1", "HITL 2", "HITL 1.5"]:
                    print(f"⚠️ HUMAN BLOCKING: {g.req_id} at {g.gate}")
                    print(f"   Action: {g.action_required}")
                    print()
        else:
            print("✅ No pending human actions — workflow is not blocked")
            print()

    if args.update_memory:
        update_memory_bank(report)
        print("[GATE NOTIFICATION] Updated memory-bank files")

    # Exit code: 0 = no blocking gates, 1 = some gates pending
    sys.exit(0 if not report.has_pending_gates() else 0)  # Always exit 0, info only


if __name__ == "__main__":
    main()