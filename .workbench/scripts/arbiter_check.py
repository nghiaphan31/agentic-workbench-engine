#!/usr/bin/env python3
"""
arbiter_check.py — Compliance Health Scanner

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/arbiter_check.py

Runs observable proxy checks for all .clinerules rules.
Converts honor-only rules into warned or enforced rules.

Usage:
  python arbiter_check.py check                    # Full scan (all 13 checks)
  python arbiter_check.py check-session            # Lightweight (CRITICAL only)
  python arbiter_check.py check-session --block-on-critical
  python arbiter_check.py check --rule SLC-1       # Single rule check
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
STATE_JSON = REPO_ROOT / "state.json"
HOT_CONTEXT = REPO_ROOT / "memory-bank" / "hot-context"
ARCHIVE_COLD = REPO_ROOT / "memory-bank" / "archive-cold"
DOCS_CONVERSATIONS = REPO_ROOT / "docs" / "conversations"
SRC_DIR = REPO_ROOT / "src"


@dataclass
class CheckResult:
    rule: str
    status: str  # CRITICAL, WARNING, INFO, OK
    message: str
    suggestion: str = ""
    details: list = field(default_factory=list)


def load_state() -> Optional[dict]:
    if not STATE_JSON.exists():
        return None
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_git(args: list, cwd=None) -> tuple:
    """Run a git command, return (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip(), result.returncode
    except Exception:
        return "", 1


def check_startup_protocol() -> CheckResult:
    """SLC-1: Check if activeContext.md was recently updated (proxy for startup ran)."""
    active_ctx = HOT_CONTEXT / "activeContext.md"
    if not active_ctx.exists():
        return CheckResult(
            rule="SLC-1",
            status="WARNING",
            message="activeContext.md does not exist — startup protocol may not have run",
            suggestion="Run startup protocol: CHECK → CREATE → READ activeContext.md"
        )
    mtime = datetime.fromtimestamp(active_ctx.stat().st_mtime, tz=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
    state = load_state()
    if state and state.get("state") not in ["INIT", None] and age_minutes > 60:
        return CheckResult(
            rule="SLC-1",
            status="WARNING",
            message=f"activeContext.md last modified {age_minutes:.0f} minutes ago — startup protocol may have been skipped",
            suggestion="Run startup protocol: read activeContext.md and progress.md before acting"
        )
    return CheckResult(rule="SLC-1", status="OK", message="activeContext.md recently updated (startup likely ran)")


def check_audit_log_immutability() -> CheckResult:
    """SLC-2: Check if any docs/conversations/ files have been tampered with."""
    if not DOCS_CONVERSATIONS.exists():
        return CheckResult(rule="SLC-2", status="OK", message="No audit logs found (ok — none created yet)")
    
    tampered = []
    for md_file in DOCS_CONVERSATIONS.glob("*.md"):
        if md_file.name == ".gitkeep":
            continue
        # Check if file is tracked by git and if content matches git object
        stdout, rc = run_git(["log", "--oneline", "-1", "--", str(md_file.relative_to(REPO_ROOT))])
        if rc != 0 or not stdout:
            continue  # Not tracked yet, skip
        # Get the git hash of the file at last commit
        stdout2, rc2 = run_git(["show", f"HEAD:{md_file.relative_to(REPO_ROOT)}"])
        if rc2 == 0:
            try:
                current_content = md_file.read_text(encoding="utf-8")
                if current_content != stdout2:
                    tampered.append(md_file.name)
            except Exception:
                pass
    
    if tampered:
        return CheckResult(
            rule="SLC-2",
            status="CRITICAL",
            message=f"Audit log tampering detected: {tampered}",
            suggestion="Restore tampered files from git: git checkout HEAD -- docs/conversations/",
            details=tampered
        )
    return CheckResult(rule="SLC-2", status="OK", message="Audit logs intact (no tampering detected)")


def check_handoff_read() -> CheckResult:
    """HND-1: Check if handoff-state.md was recently read (proxy: mtime vs last commit)."""
    handoff = HOT_CONTEXT / "handoff-state.md"
    if not handoff.exists():
        return CheckResult(rule="HND-1", status="OK", message="handoff-state.md does not exist (ok — no handoff pending)")
    
    mtime = datetime.fromtimestamp(handoff.stat().st_mtime, tz=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
    
    # If handoff was modified recently but not read (heuristic: mtime > 30 min ago)
    if age_minutes > 30:
        return CheckResult(
            rule="HND-1",
            status="WARNING",
            message=f"handoff-state.md last modified {age_minutes:.0f} minutes ago — may not have been read this session",
            suggestion="Read handoff-state.md before taking any action (Rule HND-1)"
        )
    return CheckResult(rule="HND-1", status="OK", message="handoff-state.md recently accessed")


def check_handoff_freshness() -> CheckResult:
    """HND-2: Check if handoff-state.md contains stale sprint markers."""
    handoff = HOT_CONTEXT / "handoff-state.md"
    progress = HOT_CONTEXT / "progress.md"
    
    if not handoff.exists():
        return CheckResult(rule="HND-2", status="OK", message="No handoff-state.md (ok)")
    
    try:
        handoff_content = handoff.read_text(encoding="utf-8")
        # Check for sprint markers in handoff that predate current sprint
        sprint_matches = re.findall(r"sprint[-_](\d+)", handoff_content, re.IGNORECASE)
        if sprint_matches and progress.exists():
            progress_content = progress.read_text(encoding="utf-8")
            current_sprint_matches = re.findall(r"sprint[-_](\d+)", progress_content, re.IGNORECASE)
            if current_sprint_matches:
                current_sprint = max(int(s) for s in current_sprint_matches)
                handoff_sprints = [int(s) for s in sprint_matches]
                stale = [s for s in handoff_sprints if s < current_sprint]
                if stale:
                    return CheckResult(
                        rule="HND-2",
                        status="WARNING",
                        message=f"handoff-state.md contains stale sprint markers: sprint-{stale}",
                        suggestion="Run: python .workbench/scripts/memory_rotator.py rotate"
                    )
    except Exception:
        pass
    
    return CheckResult(rule="HND-2", status="OK", message="handoff-state.md sprint markers are current")


def check_cold_zone_access() -> CheckResult:
    """MEM-1: Check git log for direct edits to archive-cold/ files."""
    stdout, rc = run_git(["log", "--oneline", "--diff-filter=M", "--", "memory-bank/archive-cold/"])
    if rc != 0:
        return CheckResult(rule="MEM-1", status="INFO", message="Cannot check git log (not a git repo or no commits)")
    
    if stdout:
        lines = [l for l in stdout.split("\n") if l.strip()]
        return CheckResult(
            rule="MEM-1",
            status="CRITICAL",
            message=f"Direct writes to archive-cold/ detected in git history ({len(lines)} commits)",
            suggestion="archive-cold/ is read-only for agents. Use archive-query MCP tool to read. Use memory_rotator.py to write.",
            details=lines[:5]
        )
    return CheckResult(rule="MEM-1", status="OK", message="No direct writes to archive-cold/ detected")


def check_decision_log_updated() -> CheckResult:
    """MEM-2: Check if decisionLog.md was updated this sprint."""
    decision_log = HOT_CONTEXT / "decisionLog.md"
    progress = HOT_CONTEXT / "progress.md"
    
    if not decision_log.exists():
        return CheckResult(
            rule="MEM-2",
            status="WARNING",
            message="decisionLog.md does not exist",
            suggestion="Create decisionLog.md and log significant decisions in ADR format"
        )
    
    mtime = datetime.fromtimestamp(decision_log.stat().st_mtime, tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - mtime).total_seconds() / 86400
    
    if age_days > 7:
        return CheckResult(
            rule="MEM-2",
            status="WARNING",
            message=f"decisionLog.md last modified {age_days:.0f} days ago — no decisions logged this sprint",
            suggestion="Log significant decisions in ADR format in decisionLog.md (Rule MEM-2)"
        )
    return CheckResult(rule="MEM-2", status="OK", message=f"decisionLog.md updated {age_days:.1f} days ago")


def check_codebase_memory_index_scope() -> CheckResult:
    """MEM-3a: Check that memory-bank/ directories have NOT been indexed into codebase-memory MCP."""
    # Try to call codebase-memory index_status
    try:
        result = subprocess.run(
            ["codebase-memory", "index_status"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode != 0:
            # Binary not available or command failed — report WARNING
            return CheckResult(
                rule="MEM-3a",
                status="WARNING",
                message="codebase-memory index_status unavailable or failed",
                suggestion="Ensure codebase-memory MCP is properly installed and reachable"
            )
        
        output = result.stdout.strip()
        if not output:
            # No indexed projects — trivially ok
            return CheckResult(rule="MEM-3a", status="OK", message="No indexed projects found in codebase-memory")
        
        # Parse output — each line is a project entry with path
        # Expected format: "project_name | /path/to/project" or similar
        # We check each line for memory-bank/ or archive-cold/ paths
        violations = []
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Check if the line contains a memory-bank path
            if "memory-bank/" in line:
                violations.append(line)
        
        if violations:
            return CheckResult(
                rule="MEM-3a",
                status="CRITICAL",
                message=f"memory-bank/ indexed into codebase-memory MCP — Cold Zone Firewall violation",
                suggestion="Use archive-query MCP tool to access Cold Zone. Remove memory-bank/ from codebase-memory index.",
                details=violations[:5]
            )
        
        return CheckResult(rule="MEM-3a", status="OK", message="No memory-bank/ paths indexed in codebase-memory")
        
    except FileNotFoundError:
        return CheckResult(
            rule="MEM-3a",
            status="WARNING",
            message="codebase-memory binary not found",
            suggestion="Install codebase-memory MCP or ensure it is in PATH"
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            rule="MEM-3a",
            status="WARNING",
            message="codebase-memory index_status timed out",
            suggestion="codebase-memory may be busy — retry later"
        )
    except Exception as e:
        return CheckResult(
            rule="MEM-3a",
            status="WARNING",
            message=f"Failed to check codebase-memory index status: {e}",
            suggestion="Investigate codebase-memory MCP availability"
        )


def check_crash_checkpoint() -> CheckResult:
    """CR-1: Check for stale ACTIVE crash checkpoint."""
    checkpoint = HOT_CONTEXT / "session-checkpoint.md"
    
    if not checkpoint.exists():
        return CheckResult(rule="CR-1", status="INFO", message="No session-checkpoint.md found (ok)")
    
    try:
        content = checkpoint.read_text(encoding="utf-8")
        if "status: ACTIVE" in content or "status:ACTIVE" in content:
            mtime = datetime.fromtimestamp(checkpoint.stat().st_mtime, tz=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
            if age_minutes > 30:
                return CheckResult(
                    rule="CR-1",
                    status="WARNING",
                    message=f"Stale ACTIVE checkpoint detected (last heartbeat {age_minutes:.0f} minutes ago)",
                    suggestion="Run: python .workbench/scripts/crash_recovery.py status — offer to resume from checkpoint"
                )
    except Exception:
        pass
    
    return CheckResult(rule="CR-1", status="INFO", message="No active crash checkpoint found (ok)")


def check_dependency_blocked_mode() -> CheckResult:
    """DEP-3: Check for non-Orchestrator commits during DEPENDENCY_BLOCKED state."""
    state = load_state()
    if not state:
        return CheckResult(rule="DEP-3", status="INFO", message="No state.json found")
    
    if state.get("state") != "DEPENDENCY_BLOCKED":
        return CheckResult(rule="DEP-3", status="OK", message="Not in DEPENDENCY_BLOCKED state")
    
    # Check for commits since the block began
    blocked_at = None
    registry = state.get("feature_registry", {})
    active_req = state.get("active_req_id")
    if active_req and active_req in registry:
        # Try to find when block started from registry
        pass
    
    # Check recent commits for non-Orchestrator work
    stdout, rc = run_git(["log", "--oneline", "-5", "--format=%s"])
    if rc == 0 and stdout:
        commits = stdout.split("\n")
        suspicious = [c for c in commits if c.strip() and not any(
            keyword in c.lower() for keyword in ["chore", "docs", "monitor", "dependency"]
        )]
        if suspicious:
            return CheckResult(
                rule="DEP-3",
                status="CRITICAL",
                message=f"Non-Orchestrator commits detected during DEPENDENCY_BLOCKED state",
                suggestion="Only the Orchestrator Agent may act during DEPENDENCY_BLOCKED. Revert non-Orchestrator commits.",
                details=suspicious[:3]
            )
    
    return CheckResult(rule="DEP-3", status="WARNING", message="DEPENDENCY_BLOCKED — only Orchestrator Agent should be active",
                      suggestion="Monitor dependency states and report to human via Roo Chat")


def check_file_access_constraints() -> CheckResult:
    """FAC-1: Check staged files against current stage's allowed write scope."""
    state = load_state()
    if not state:
        return CheckResult(rule="FAC-1", status="INFO", message="No state.json found — cannot check file access constraints")
    
    stage = state.get("stage")
    if stage is None:
        return CheckResult(rule="FAC-1", status="OK", message="No active stage — file access constraints not applicable")
    
    # Get staged files
    stdout, rc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if rc != 0 or not stdout:
        return CheckResult(rule="FAC-1", status="OK", message="No staged files to check")
    
    staged_files = [f.strip() for f in stdout.split("\n") if f.strip()]
    
    # Stage-to-allowed-write-paths mapping
    stage_allowed = {
        1: ["features/", "_inbox/"],           # Architect: features + inbox
        2: ["tests/unit/"],                     # Test Engineer Stage 2: unit tests only
        3: ["src/"],                            # Developer: src only
        4: [],                                  # Orchestrator/Reviewer: read-only
    }
    
    allowed_prefixes = stage_allowed.get(stage, [])
    if not allowed_prefixes:
        # Stage 4 is read-only — any staged file is a violation
        if staged_files:
            return CheckResult(
                rule="FAC-1",
                status="CRITICAL",
                message=f"Stage {stage} is read-only but {len(staged_files)} files are staged for write",
                suggestion=f"Unstage all files: git reset HEAD",
                details=staged_files[:5]
            )
        return CheckResult(rule="FAC-1", status="OK", message=f"Stage {stage}: no staged files (ok)")
    
    violations = []
    for f in staged_files:
        if not any(f.startswith(prefix) for prefix in allowed_prefixes):
            # Allow memory-bank and docs writes for all stages (session management)
            if not any(f.startswith(p) for p in ["memory-bank/", "docs/conversations/", "state.json"]):
                violations.append(f)
    
    if violations:
        return CheckResult(
            rule="FAC-1",
            status="CRITICAL",
            message=f"Stage {stage} file access violation: {len(violations)} files outside allowed scope",
            suggestion=f"Stage {stage} may only write to: {allowed_prefixes}. Unstage: git reset HEAD -- <file>",
            details=violations[:5]
        )
    
    return CheckResult(rule="FAC-1", status="OK", message=f"Stage {stage}: all staged files within allowed scope")


def check_live_imports_from_non_merged() -> CheckResult:
    """TRC-2: Scan src/ for imports from non-MERGED features."""
    state = load_state()
    if not state:
        return CheckResult(rule="TRC-2", status="INFO", message="No state.json found")
    
    registry = state.get("feature_registry", {})
    non_merged = {req_id: entry for req_id, entry in registry.items() 
                  if entry.get("state") != "MERGED"}
    
    if not non_merged or not SRC_DIR.exists():
        return CheckResult(rule="TRC-2", status="OK", message="No non-MERGED features or no src/ directory")
    
    suspect_imports = []
    import_pattern = re.compile(r'^\s*(import|from|require)\s+["\']?([^\s"\']+)', re.MULTILINE)
    
    for src_file in SRC_DIR.rglob("*"):
        if src_file.is_file() and src_file.suffix in [".ts", ".js", ".tsx", ".jsx", ".py"]:
            try:
                content = src_file.read_text(encoding="utf-8")
                for match in import_pattern.finditer(content):
                    module = match.group(2).lower()
                    for req_id in non_merged:
                        slug = registry[req_id].get("branch", "").split("/")[-1].lower()
                        if slug and slug in module:
                            suspect_imports.append(f"{src_file.name}: imports '{module}' (from {req_id} state={non_merged[req_id].get('state')})")
            except Exception:
                pass
    
    if suspect_imports:
        return CheckResult(
            rule="TRC-2",
            status="WARNING",
            message=f"Suspect imports from non-MERGED features detected",
            suggestion="Use stub interfaces instead of live imports from non-MERGED features (Rule TRC-2)",
            details=suspect_imports[:5]
        )
    return CheckResult(rule="TRC-2", status="OK", message="No suspect imports from non-MERGED features detected")


def check_regression_failures_populated() -> CheckResult:
    """REG-1: Check if regression_failures is populated when REGRESSION_RED."""
    state = load_state()
    if not state:
        return CheckResult(rule="REG-1", status="INFO", message="No state.json found")
    
    if state.get("regression_state") != "REGRESSION_RED":
        return CheckResult(rule="REG-1", status="OK", message="Not in REGRESSION_RED state")
    
    failures = state.get("regression_failures", [])
    if not failures:
        return CheckResult(
            rule="REG-1",
            status="WARNING",
            message="REGRESSION_RED but regression_failures is empty — no actionable failure data",
            suggestion="Run: python .workbench/scripts/test_orchestrator.py run --scope full --set-state"
        )
    return CheckResult(rule="REG-1", status="OK", message=f"regression_failures populated with {len(failures)} entries")


def check_arbiter_capabilities_registered() -> CheckResult:
    """CMD-TRANSITION: Check if arbiter_capabilities are registered."""
    state = load_state()
    if not state:
        return CheckResult(rule="CMD-TRANSITION", status="INFO", message="No state.json found")
    
    capabilities = state.get("arbiter_capabilities", {})
    all_false = all(not v for v in capabilities.values())
    
    if all_false:
        return CheckResult(
            rule="CMD-TRANSITION",
            status="WARNING",
            message="All arbiter_capabilities are false — Phase A not configured",
            suggestion="Run: python workbench-cli.py register-arbiter"
        )
    
    false_caps = [k for k, v in capabilities.items() if not v]
    if false_caps:
        return CheckResult(
            rule="CMD-TRANSITION",
            status="WARNING",
            message=f"Some arbiter_capabilities not registered: {false_caps}",
            suggestion="Run: python workbench-cli.py register-arbiter"
        )
    
    return CheckResult(rule="CMD-TRANSITION", status="OK", message="All arbiter_capabilities registered")


def check_forbidden_self_declaration() -> CheckResult:
    """FOR-1: Check for self-declaration in handoff-state.md when state != GREEN."""
    state = load_state()
    handoff = HOT_CONTEXT / "handoff-state.md"
    
    if not state or not handoff.exists():
        return CheckResult(rule="FOR-1", status="OK", message="No state or handoff to check")
    
    current_state = state.get("state", "")
    if current_state in ["GREEN", "MERGED", "INIT"]:
        return CheckResult(rule="FOR-1", status="OK", message=f"State is {current_state} — self-declaration check not applicable")
    
    try:
        content = handoff.read_text(encoding="utf-8").lower()
        self_declaration_markers = ["completed", "done", "finished", "feature complete", "implementation complete"]
        found = [m for m in self_declaration_markers if m in content]
        if found:
            return CheckResult(
                rule="FOR-1",
                status="WARNING",
                message=f"Possible self-declaration in handoff-state.md (state={current_state}, markers={found})",
                suggestion="Completion requires Arbiter-confirmed GREEN state. Do not self-declare completion."
            )
    except Exception:
        pass
    
    return CheckResult(rule="FOR-1", status="OK", message="No self-declaration markers detected")


# Check registry mapping rule IDs to check functions
CHECK_REGISTRY = {
    "SLC-1":          check_startup_protocol,
    "SLC-2":          check_audit_log_immutability,
    "HND-1":          check_handoff_read,
    "HND-2":          check_handoff_freshness,
    "MEM-1":          check_cold_zone_access,
    "MEM-2":          check_decision_log_updated,
    "MEM-3a":         check_codebase_memory_index_scope,
    "CR-1":           check_crash_checkpoint,
    "DEP-3":          check_dependency_blocked_mode,
    "FAC-1":          check_file_access_constraints,
    "TRC-2":          check_live_imports_from_non_merged,
    "REG-1":          check_regression_failures_populated,
    "CMD-TRANSITION": check_arbiter_capabilities_registered,
    "FOR-1":          check_forbidden_self_declaration,
}

# Checks run in check-session mode (lightweight — 5 critical rules for session startup)
# NOTE: SESSION_CHECKS includes CR-1 which is WARNING level (stale checkpoint detection)
#       SLC-2, MEM-1, MEM-3a, DEP-3, FAC-1 are CRITICAL level
SESSION_CHECKS = ["SLC-2", "MEM-1", "MEM-3a", "DEP-3", "FAC-1", "CR-1"]


def format_result(result: CheckResult) -> str:
    """Format a CheckResult for display."""
    lines = []
    status_prefix = {
        "CRITICAL": "[CRITICAL]",
        "WARNING":  "[WARNING] ",
        "INFO":     "[INFO]    ",
        "OK":       "[OK]      ",
    }.get(result.status, f"[{result.status}]")
    
    lines.append(f"{status_prefix} {result.rule} — {result.message}")
    if result.suggestion:
        lines.append(f"  SUGGESTION: {result.suggestion}")
    if result.details:
        for d in result.details[:3]:
            lines.append(f"    - {d}")
    return "\n".join(lines)


def get_memory_systems_banner() -> str:
    """
    MEM-3/MEM-3a boundary awareness banner.
    
    Displays at the start of check-session output to remind agents of the
    boundary between codebase-memory (code structure/search) and memory-bank/
    (project state). This is a human-factor mitigation — even with rules
    in place, agents under time pressure may not recall Section 8.4.
    """
    return """[INFO]  MEMORY SYSTEMS REMINDER (MEM-3 / MEM-3a)
[INFO]  ─────────────────────────────────────────────────
[INFO]  • `codebase-memory` = code structure/search only
[INFO]  • `memory-bank/` = project state (use `archive-query` MCP for Cold Zone)
[INFO]  ─────────────────────────────────────────────────"""


def run_checks(rules: list = None, session_mode: bool = False) -> list:
    """Run specified checks (or all checks). Returns list of CheckResults."""
    if session_mode:
        checks_to_run = SESSION_CHECKS
    elif rules:
        checks_to_run = [r for r in rules if r in CHECK_REGISTRY]
    else:
        checks_to_run = list(CHECK_REGISTRY.keys())
    
    results = []
    for rule_id in checks_to_run:
        check_fn = CHECK_REGISTRY.get(rule_id)
        if check_fn:
            try:
                result = check_fn()
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    rule=rule_id,
                    status="WARNING",
                    message=f"Check failed with exception: {e}",
                    suggestion="Investigate arbiter_check.py for this rule"
                ))
    return results


def main():
    parser = argparse.ArgumentParser(description="Arbiter Compliance Health Scanner")
    subparsers = parser.add_subparsers(dest="command")
    
    # check command
    check_parser = subparsers.add_parser("check", help="Run full compliance scan")
    check_parser.add_argument("--rule", help="Check a single rule (e.g., SLC-1)")
    
    # check-session command
    session_parser = subparsers.add_parser("check-session", help="Lightweight session-start check (CRITICAL only)")
    session_parser.add_argument("--block-on-critical", action="store_true", help="Exit 1 if any CRITICAL violations found")
    
    args = parser.parse_args()
    
    if args.command == "check":
        rules = [args.rule] if args.rule else None
        results = run_checks(rules=rules)
        
        print("[ARBITER CHECK] Running compliance health scan...")
        print()
        
        for result in results:
            if result.status != "OK":
                print(format_result(result))
                print()
        
        criticals = [r for r in results if r.status == "CRITICAL"]
        warnings = [r for r in results if r.status == "WARNING"]
        infos = [r for r in results if r.status == "INFO"]
        oks = [r for r in results if r.status == "OK"]
        
        print(f"[ARBITER CHECK] Scan complete: {len(criticals)} CRITICAL, {len(warnings)} WARNING, {len(infos)} INFO, {len(oks)} OK")
        
        if criticals:
            print(f"[ARBITER CHECK] BLOCKED: {len(criticals)} critical violations require resolution")
            sys.exit(1)
        elif warnings:
            print(f"[ARBITER CHECK] WARNING: {len(warnings)} warnings — review recommended")
            sys.exit(0)
        else:
            print(f"[ARBITER CHECK] PASSED: All checks OK")
            sys.exit(0)
    
    elif args.command == "check-session":
        results = run_checks(session_mode=True)
        
        print(get_memory_systems_banner())
        print()
        print("[ARBITER CHECK] Running session-start compliance scan...")
        print()
        
        criticals = [r for r in results if r.status == "CRITICAL"]
        warnings = [r for r in results if r.status == "WARNING"]
        
        for result in results:
            if result.status in ["CRITICAL", "WARNING"]:
                print(format_result(result))
                print()
        
        if criticals:
            print(f"[ARBITER CHECK] {len(criticals)} CRITICAL violations detected")
            if args.block_on_critical:
                print("[ARBITER CHECK] BLOCKED: Critical violations require resolution before proceeding")
                sys.exit(1)
        else:
            print(f"[ARBITER CHECK] No CRITICAL violations — proceeding")
        
        if warnings:
            print(f"[ARBITER CHECK] {len(warnings)} WARNING violations — acknowledge and log to handoff-state.md")
        
        sys.exit(0)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
