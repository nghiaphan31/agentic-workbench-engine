#!/usr/bin/env python3
"""
audit_logger.py — The Arbiter's Audit Trail Writer

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/audit_logger.py

Saves immutable session metadata to docs/conversations/
Called by the Close Protocol in .clinerules

Usage:
  python audit_logger.py save --session-id {id} --branch {branch}
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

DOCS_CONVERSATIONS_PATH = Path(__file__).parent.parent.parent / "docs" / "conversations"
STATE_JSON_PATH = Path(__file__).parent.parent.parent / "state.json"


def load_state():
    if not STATE_JSON_PATH.exists():
        return {}
    with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(session_id, branch):
    """Save session metadata as immutable timestamped file."""
    DOCS_CONVERSATIONS_PATH.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M_%S")
    filename = f"{timestamp}_{session_id}.md"
    filepath = DOCS_CONVERSATIONS_PATH / filename

    state = load_state()

    content = f"""# Session Audit Log

**Session ID:** {session_id}
**Branch:** {branch}
**Timestamp:** {datetime.now(timezone.utc).isoformat()}
**Recorded By:** audit_logger.py

---

## Session Metadata

| Field | Value |
|---|---|
| Session ID | {session_id} |
| Branch | {branch} |
| Timestamp | {datetime.now(timezone.utc).isoformat()} |
| Active REQ-ID | {state.get('active_req_id', 'N/A')} |
| Pipeline State | {state.get('state', 'N/A')} |
| Stage | {state.get('stage', 'N/A')} |

---

## State Snapshot

```json
{json.dumps(state, indent=2)}
```

---

## Notes

_(Add session notes here)_

---

*This file is immutable once created. Do not edit.*
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"[AUDIT LOGGER] Session saved: {filename}")
    print(f"  Path: {filepath}")
    return filepath


def list_sessions():
    """List all audit log files."""
    if not DOCS_CONVERSATIONS_PATH.exists():
        print("No audit logs found")
        return []

    files = sorted(DOCS_CONVERSATIONS_PATH.glob("*.md"), reverse=True)
    print(f"[AUDIT LOGGER] {len(files)} session(s) recorded:")
    for f in files:
        print(f"  - {f.name}")

    return files


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Audit Logger")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    save_parser = subparsers.add_parser("save", help="Save session metadata to audit trail")
    save_parser.add_argument("--session-id", required=True, help="Session ID (UUID or generated)")
    save_parser.add_argument("--branch", required=True, help="Current git branch")

    subparsers.add_parser("list", help="List all audit log files")

    args = parser.parse_args()

    if args.command == "save":
        filepath = save_session(args.session_id, args.branch)
        print(f"\nAudit trail entry created at:\n  {filepath}")
        sys.exit(0)

    elif args.command == "list":
        list_sessions()
        sys.exit(0)

    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()