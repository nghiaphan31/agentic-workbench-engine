#!/usr/bin/env python3
"""
dependency_monitor.py — The Arbiter's Dependency Monitor

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/dependency_monitor.py

Polls state.json.feature_registry on every MERGED event.
Auto-unblocks features in DEPENDENCY_BLOCKED state when all depends_on entries reach MERGED.

Usage:
  python dependency_monitor.py check-unblock
  python dependency_monitor.py status REQ-001
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

STATE_JSON_PATH = Path(__file__).parent.parent.parent / "state.json"
HANDOFF_PATH = Path(__file__).parent.parent.parent / "memory-bank" / "hot-context" / "handoff-state.md"


def load_state():
    if not STATE_JSON_PATH.exists():
        return None
    with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def check_unblock():
    """Check all DEPENDENCY_BLOCKED features and auto-unblock if deps are satisfied."""
    state = load_state()
    if not state:
        print("ERROR: state.json not found", file=sys.stderr)
        sys.exit(1)

    feature_registry = state.get("feature_registry", {})
    unblocked = []
    still_blocked = []

    for req_id, info in feature_registry.items():
        if info.get("state") == "DEPENDENCY_BLOCKED":
            depends_on = info.get("depends_on", [])
            all_merged = all(
                feature_registry.get(dep, {}).get("state") == "MERGED"
                for dep in depends_on
            )

            if all_merged:
                info["state"] = "RED"  # Transition to RED for test re-run
                unblocked.append(req_id)
                print(f"[DEPENDENCY_MONITOR] Unblocked: {req_id}")
                print(f"  All dependencies satisfied: {depends_on}")
            else:
                unmet = [dep for dep in depends_on if feature_registry.get(dep, {}).get("state") != "MERGED"]
                still_blocked.append((req_id, unmet))
                print(f"[DEPENDENCY_MONITOR] Still blocked: {req_id}")
                print(f"  Unmet deps: {unmet}")

    if unblocked:
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        state["last_updated_by"] = "dependency_monitor.py"
        save_state(state)

        # Write unblock report to handoff-state.md
        write_unblock_report(unblocked)

    return {"unblocked": unblocked, "still_blocked": [x[0] for x in still_blocked]}


def write_unblock_report(unblocked_features):
    """Write unblock report to handoff-state.md."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"""
## Dependency Unblock Report [{timestamp}]
- **Triggered by:** dependency_monitor.py check-unblock
- **Unblocked Features:** {', '.join(unblocked_features) if unblocked_features else 'None'}
- **Action:** Features transitioned from DEPENDENCY_BLOCKED to RED. Test Engineer Agent should re-confirm RED state.

---
"""

    if HANDOFF_PATH.exists():
        with open(HANDOFF_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# handoff-state.md — Inter-Agent Handoff Message Bus\n\n"

    with open(HANDOFF_PATH, "w", encoding="utf-8") as f:
        f.write(content + entry)


def status(req_id):
    """Check dependency status for a specific feature."""
    state = load_state()
    if not state:
        print("ERROR: state.json not found", file=sys.stderr)
        sys.exit(1)

    feature_registry = state.get("feature_registry", {})
    info = feature_registry.get(req_id)

    if not info:
        print(f"ERROR: {req_id} not found in feature_registry", file=sys.stderr)
        sys.exit(1)

    print(f"[DEPENDENCY_MONITOR] Status for {req_id}")
    print(f"  State: {info.get('state')}")
    print(f"  Depends On: {info.get('depends_on', [])}")

    depends_on = info.get("depends_on", [])
    for dep in depends_on:
        dep_info = feature_registry.get(dep, {})
        dep_state = dep_info.get("state", "UNKNOWN")
        print(f"    - {dep}: {dep_state}")

    if info.get("state") == "DEPENDENCY_BLOCKED":
        unmet = [dep for dep in depends_on if feature_registry.get(dep, {}).get("state") != "MERGED"]
        print(f"  Status: BLOCKED (unmet: {unmet})")
    elif info.get("state") == "MERGED":
        print(f"  Status: All dependencies satisfied")


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Dependency Monitor")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("check-unblock", help="Check all blocked features and auto-unblock if deps satisfied")

    status_parser = subparsers.add_parser("status", help="Check dependency status for a specific feature")
    status_parser.add_argument("req_id", help="REQ-ID to check (e.g., REQ-001)")

    args = parser.parse_args()

    if args.command == "check-unblock":
        result = check_unblock()
        print(f"\n[DEPENDENCY_MONITOR] Summary")
        print(f"  Unblocked: {len(result['unblocked'])}")
        print(f"  Still Blocked: {len(result['still_blocked'])}")
        sys.exit(0)

    elif args.command == "status":
        status(args.req_id)
        sys.exit(0)

    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()