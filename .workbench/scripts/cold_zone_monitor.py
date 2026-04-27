#!/usr/bin/env python3
"""
cold_zone_monitor.py — Cold Zone Access Detection Monitor

Owner: The Arbiter (Layer 2)
Version: 2.2
Location: .workbench/scripts/cold_zone_monitor.py

Detects direct access attempts to memory-bank/archive-cold/ (Cold Zone).
The MCP server (archive-query) is the primary enforcement mechanism.
This monitor is a detective control to detect bypass attempts.

Usage:
    python cold_zone_monitor.py check          # Run on-demand check
    python cold_zone_monitor.py monitor         # Run continuous daemon mode (Linux only)
    python cold_zone_monitor.py status          # Show last check results
    python cold_zone_monitor.py clear           # Clear audit log
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
ARCHIVE_COLD = REPO_ROOT / "memory-bank" / "archive-cold"
AUDIT_LOG_DIR = REPO_ROOT / ".workbench" / "logs"
COLD_ZONE_AUDIT = AUDIT_LOG_DIR / "cold_zone_access_audit.jsonl"
BASELINE_FILE = AUDIT_LOG_DIR / "cold_zone_baseline.json"


def ensure_dirs():
    """Ensure required directories exist."""
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_file_metadata(path: Path) -> dict:
    """Get metadata for a single file."""
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "is_file": path.is_file(),
        }
    except Exception as e:
        return {"path": str(path), "error": str(e)}


def scan_archive_cold() -> dict:
    """Scan archive-cold/ and return current state."""
    if not ARCHIVE_COLD.exists():
        return {"files": [], "timestamp": datetime.now(timezone.utc).isoformat()}

    files = {}
    for item in ARCHIVE_COLD.rglob("*"):
        if item.is_file():
            rel_path = str(item.relative_to(ARCHIVE_COLD))
            files[rel_path] = get_file_metadata(item)

    return {
        "files": files,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scan_root": str(ARCHIVE_COLD),
    }


def load_baseline() -> Optional[dict]:
    """Load the last known baseline."""
    if not BASELINE_FILE.exists():
        return None
    try:
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_baseline(baseline: dict):
    """Save current state as baseline."""
    ensure_dirs()
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)


def load_audit_log() -> list:
    """Load existing audit log entries."""
    if not COLD_ZONE_AUDIT.exists():
        return []
    try:
        entries = []
        with open(COLD_ZONE_AUDIT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
    except Exception:
        return []


def append_audit_log(entry: dict):
    """Append a new entry to the audit log."""
    ensure_dirs()
    with open(COLD_ZONE_AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def detect_direct_access(current_scan: dict, baseline: Optional[dict]) -> list:
    """
    Detect direct access attempts by comparing current scan vs baseline.
    
    Direct access is suspected when:
    - New files appear that weren't created by memory_rotator.py
    - Existing files are modified but not by memory_rotator.py
    - Files are deleted directly
    
    Returns list of detected access events.
    """
    if baseline is None:
        # First run - just save baseline, no detection
        return []

    violations = []
    baseline_files = baseline.get("files", {})
    current_files = current_scan.get("files", {})

    baseline_paths = set(baseline_files.keys())
    current_paths = set(current_files.keys())

    # Detect new files
    new_files = current_paths - baseline_paths
    for rel_path in new_files:
        file_meta = current_files[rel_path]
        # Check if memory_rotator.py created this (heuristic: recent mtime + specific pattern)
        violations.append({
            "type": "CREATE",
            "path": rel_path,
            "mtime": file_meta.get("mtime"),
            "size": file_meta.get("size"),
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "note": "New file detected - verify it was created by memory_rotator.py"
        })

    # Detect deleted files
    deleted_files = baseline_paths - current_paths
    for rel_path in deleted_files:
        file_meta = baseline_files[rel_path]
        violations.append({
            "type": "DELETE",
            "path": rel_path,
            "mtime": file_meta.get("mtime"),
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "note": "File was deleted - archive-cold/ should not be modified directly"
        })

    # Detect modified files
    for rel_path in baseline_paths & current_paths:
        baseline_meta = baseline_files[rel_path]
        current_meta = current_files[rel_path]
        
        # Check mtime or size changed
        if (baseline_meta.get("mtime") != current_meta.get("mtime") or
            baseline_meta.get("size") != current_meta.get("size")):
            violations.append({
                "type": "MODIFY",
                "path": rel_path,
                "old_mtime": baseline_meta.get("mtime"),
                "new_mtime": current_meta.get("mtime"),
                "old_size": baseline_meta.get("size"),
                "new_size": current_meta.get("size"),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "note": "File was modified - verify change was made by memory_rotator.py"
            })

    return violations


def check_access_via_audit_log(since: Optional[str] = None) -> list:
    """
    Check audit log for direct access attempts.
    
    Args:
        since: ISO timestamp string. If provided, only return entries after this time.
               If None, return all entries (for backward compatibility).
    
    Returns:
        List of audit log entries indicating direct access.
    """
    entries = load_audit_log()
    
    if since is None:
        return entries
    
    # Filter entries newer than 'since'
    filtered = []
    for entry in entries:
        entry_time = entry.get("detected_at", "")
        if entry_time >= since:
            filtered.append(entry)
    return filtered


def run_check() -> dict:
    """
    Run a single check: compare current state vs baseline, log violations.
    
    Returns:
        dict with 'violations' list and 'summary' string.
    """
    ensure_dirs()
    
    current_scan = scan_archive_cold()
    baseline = load_baseline()
    
    violations = detect_direct_access(current_scan, baseline)
    
    # Log violations to audit log
    for violation in violations:
        append_audit_log(violation)
    
    # Update baseline
    save_baseline(current_scan)
    
    return {
        "violations": violations,
        "current_scan": current_scan,
        "baseline_was_none": baseline is None,
        "summary": f"Found {len(violations)} violation(s)" if violations else "No violations detected"
    }


def clear_audit_log():
    """Clear the audit log after it has been checked."""
    if COLD_ZONE_AUDIT.exists():
        COLD_ZONE_AUDIT.unlink()
    return True


def show_status() -> dict:
    """Show current monitor status."""
    baseline = load_baseline()
    recent_entries = load_audit_log()
    
    return {
        "archive_cold_exists": ARCHIVE_COLD.exists(),
        "baseline_exists": baseline is not None,
        "baseline_timestamp": baseline.get("timestamp") if baseline else None,
        "audit_log_entries": len(recent_entries),
        "recent_violations": recent_entries[-10:] if recent_entries else [],
    }


def monitor_daemon(interval_seconds: int = 60):
    """
    Run as a daemon, periodically checking for direct access.
    
    Note: This uses simple polling. For Linux, inotify-based monitoring
    would be more efficient but requires additional dependencies.
    """
    import time
    
    print(f"[COLD ZONE MONITOR] Starting daemon mode (interval: {interval_seconds}s)")
    print(f"[COLD ZONE MONITOR] Watching: {ARCHIVE_COLD}")
    
    while True:
        try:
            result = run_check()
            if result["violations"]:
                print(f"[COLD ZONE MONITOR] {result['summary']}")
                for v in result["violations"]:
                    print(f"  - {v['type']}: {v['path']}")
            else:
                print(f"[COLD ZONE MONITOR] Check OK: {result['summary']}")
        except Exception as e:
            print(f"[COLD ZONE MONITOR] Error during check: {e}")
        
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(
        description="Cold Zone Access Detection Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python cold_zone_monitor.py check       # Run a single check
    python cold_zone_monitor.py status       # Show monitor status
    python cold_zone_monitor.py clear        # Clear audit log after reading
    python cold_zone_monitor.py monitor      # Run continuous daemon (Linux)
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # check command
    check_parser = subparsers.add_parser("check", help="Run on-demand access check")
    
    # status command
    status_parser = subparsers.add_parser("status", help="Show monitor status")
    
    # clear command
    clear_parser = subparsers.add_parser("clear", help="Clear audit log")
    
    # monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Run daemon mode")
    monitor_parser.add_argument("--interval", type=int, default=60, 
                               help="Check interval in seconds (default: 60)")
    
    args = parser.parse_args()
    
    if args.command == "check":
        result = run_check()
        print(f"[COLD ZONE MONITOR] Check complete: {result['summary']}")
        if result["baseline_was_none"]:
            print("[COLD ZONE MONITOR] First run - baseline created, no history to compare")
        if result["violations"]:
            print("[COLD ZONE MONITOR] Violations logged to audit file")
            for v in result["violations"]:
                print(f"  [{v['type']}] {v['path']} - {v.get('note', '')}")
        return 0 if not result["violations"] else 1
    
    elif args.command == "status":
        status = show_status()
        print(f"[COLD ZONE MONITOR] Status:")
        print(f"  Archive Cold exists: {status['archive_cold_exists']}")
        print(f"  Baseline exists: {status['baseline_exists']}")
        print(f"  Baseline timestamp: {status['baseline_timestamp']}")
        print(f"  Audit log entries: {status['audit_log_entries']}")
        if status["recent_violations"]:
            print(f"  Recent violations:")
            for v in status["recent_violations"][-5:]:
                print(f"    [{v.get('type', '?')}] {v.get('path', '?')} at {v.get('detected_at', '?')}")
        return 0
    
    elif args.command == "clear":
        if clear_audit_log():
            print("[COLD ZONE MONITOR] Audit log cleared")
        return 0
    
    elif args.command == "monitor":
        print("[COLD ZONE MONITOR] Daemon mode requested")
        print("[COLD ZONE MONITOR] Note: Use Ctrl+C to stop")
        monitor_daemon(interval_seconds=args.interval)
        return 0
    
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
