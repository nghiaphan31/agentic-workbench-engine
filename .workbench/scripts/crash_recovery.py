#!/usr/bin/env python3
"""
crash_recovery.py — The Arbiter's Crash Recovery Daemon

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/crash_recovery.py

Writes heartbeat to session-checkpoint.md every 5 minutes during active work.
Detects ACTIVE status on startup and offers resume.

Usage:
  python crash_recovery.py start       # Start daemon (background)
  python crash_recovery.py status     # Check current checkpoint
  python crash_recovery.py clear      # Reset checkpoint (new session)
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
import subprocess

SESSION_CHECKPOINT_PATH = Path(__file__).parent.parent.parent / "memory-bank" / "hot-context" / "session-checkpoint.md"


def read_checkpoint():
    """Read current checkpoint state."""
    if not SESSION_CHECKPOINT_PATH.exists():
        return {"status": "EMPTY"}

    content = SESSION_CHECKPOINT_PATH.read_text(encoding="utf-8")

    # Parse status from content
    if "status: ACTIVE" in content:
        # Extract session data
        session_id = extract_field(content, "session_id:")
        branch = extract_field(content, "branch:")
        commit_hash = extract_field(content, "commit_hash:")
        current_task = extract_field(content, "current_task:")
        last_heartbeat = extract_field(content, "last_heartbeat:")

        return {
            "status": "ACTIVE",
            "session_id": session_id or "unknown",
            "branch": branch or "unknown",
            "commit_hash": commit_hash or "unknown",
            "current_task": current_task or "unknown",
            "last_heartbeat": last_heartbeat or "unknown"
        }

    return {"status": "EMPTY"}


def extract_field(content, field_name):
    """Extract field value from checkpoint content."""
    for line in content.split("\n"):
        if line.strip().startswith(field_name):
            return line.split(":", 1)[1].strip()
    return None


def write_checkpoint(session_id, branch, commit_hash, current_task):
    """Write ACTIVE checkpoint."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    content = f"""# session-checkpoint.md — 5-Minute Crash Recovery Heartbeat

**Template Version:** 2.1
**Owner:** Arbiter (crash_recovery.py daemon)
**Rotation Policy:** Reset (overwritten to empty template, NOT archived) — crash recovery data is only valid for the current session

---

## Checkpoint Status

**status:** ACTIVE

---

## Session Data

Only valid when `status: ACTIVE`

- **session_id:** {session_id}
- **branch:** {branch}
- **commit_hash:** {commit_hash}
- **current_task:** {current_task}
- **last_heartbeat:** {timestamp}

---

## Crash Recovery Protocol

If `status: ACTIVE` on session start:

1. Read session data above
2. Offer to resume from the checkpoint
3. If human confirms, restore session context
4. If human declines, reset checkpoint and start fresh

---

## Notes

(TODO: Any additional checkpoint notes)
"""

    SESSION_CHECKPOINT_PATH.write_text(content, encoding="utf-8")


def clear_checkpoint():
    """Reset checkpoint to EMPTY state."""
    content = """# session-checkpoint.md — 5-Minute Crash Recovery Heartbeat

**Template Version:** 2.1
**Owner:** Arbiter (crash_recovery.py daemon)
**Rotation Policy:** Reset (overwritten to empty template, NOT archived) — crash recovery data is only valid for the current session

---

## Checkpoint Status

**status:** EMPTY

---

## Session Data

Only valid when `status: ACTIVE`

- **session_id:** (auto-generated UUID)
- **branch:** (current git branch)
- **commit_hash:** (current HEAD commit)
- **current_task:** (current task description)
- **last_heartbeat:** (YYYY-MM-DD HH:MM UTC)

---

## Crash Recovery Protocol

If `status: ACTIVE` on session start:

1. Read session data above
2. Offer to resume from the checkpoint
3. If human confirms, restore session context
4. If human declines, reset checkpoint and start fresh

---

## Notes

(TODO: Any additional checkpoint notes)
"""

    SESSION_CHECKPOINT_PATH.write_text(content, encoding="utf-8")
    print("[CRASH_RECOVERY] Checkpoint cleared")


def start_daemon(interval_seconds=300):
    """Start the heartbeat daemon."""
    # Get current git info
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=SESSION_CHECKPOINT_PATH.parent.parent.parent
        ).stdout.strip()
        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=SESSION_CHECKPOINT_PATH.parent.parent.parent
        ).stdout.strip()[:8]
    except:
        branch = "unknown"
        commit_hash = "unknown"

    session_id = str(uuid.uuid4())[:8]
    current_task = "Active development session"

    print(f"[CRASH_RECOVERY] Daemon started — interval: {interval_seconds}s")
    print(f"  Session ID: {session_id}")
    print(f"  Branch: {branch}")
    print(f"  Commit: {commit_hash}")
    print()
    print("Press Ctrl+C to stop")
    print()

    while True:
        write_checkpoint(session_id, branch, commit_hash, current_task)
        print(f"[CRASH_RECOVERY] Heartbeat written: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        time.sleep(interval_seconds)


def show_status():
    """Show current checkpoint status."""
    checkpoint = read_checkpoint()

    print(f"[CRASH_RECOVERY] Checkpoint Status: {checkpoint['status']}")

    if checkpoint["status"] == "ACTIVE":
        print(f"  Session ID: {checkpoint['session_id']}")
        print(f"  Branch: {checkpoint['branch']}")
        print(f"  Commit: {checkpoint['commit_hash']}")
        print(f"  Current Task: {checkpoint['current_task']}")
        print(f"  Last Heartbeat: {checkpoint['last_heartbeat']}")
        print()
        print("Resume available — offer to continue from this checkpoint")
    else:
        print("  No active session — fresh start")


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Crash Recovery Daemon")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("start", help="Start heartbeat daemon (5-minute intervals)")
    subparsers.add_parser("status", help="Check current checkpoint status")
    subparsers.add_parser("clear", help="Clear checkpoint and start fresh")

    args = parser.parse_args()

    if args.command == "start":
        start_daemon()
    elif args.command == "status":
        show_status()
    elif args.command == "clear":
        clear_checkpoint()
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()