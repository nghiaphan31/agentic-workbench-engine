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
import importlib.util
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
TEST_EVIDENCE_SEALS = REPO_ROOT / ".workbench" / "test_evidence" / "seals"
TEST_EVIDENCE_TRANSITIONS = REPO_ROOT / ".workbench" / "test_evidence" / "transitions"


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
    """
    MEM-1 + FOR-1(6): Check for direct access to archive-cold/.
    
    This function implements a hybrid enforcement approach:
    1. Check git log for direct edits to archive-cold/ files
    2. Check the cold_zone_monitor audit log for detected access attempts
    
    The MCP server (archive-query) is the primary enforcement mechanism.
    This check is a detective control to detect when someone tries to bypass the MCP.
    
    FOR-1(6) Enhancement: Uses cold_zone_monitor audit log to detect direct access
    attempts since last session. Clears the audit log after checking to prevent
    duplicate alerts.
    """
    # Path to cold_zone_monitor's audit log
    audit_log_path = REPO_ROOT / ".workbench" / "logs" / "cold_zone_access_audit.jsonl"
    
    # Check git log for direct edits (original MEM-1 check)
    stdout, rc = run_git(["log", "--oneline", "--diff-filter=M", "--", "memory-bank/archive-cold/"])
    git_violations = []
    if rc == 0 and stdout:
        git_violations = [l for l in stdout.split("\n") if l.strip()]
    
    # FOR-1(6): Check cold_zone_monitor audit log for direct access attempts
    audit_violations = []
    last_session_marker = None
    
    try:
        # Try to get last session marker from session-checkpoint.md
        checkpoint = HOT_CONTEXT / "session-checkpoint.md"
        if checkpoint.exists():
            content = checkpoint.read_text(encoding="utf-8")
            # Look for timestamp in checkpoint that indicates when session started
            import re
            ts_match = re.search(r"last_check:?\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", content)
            if ts_match:
                last_session_marker = ts_match.group(1)
    except Exception:
        pass
    
    # Read audit log and filter entries since last session
    if audit_log_path.exists():
        try:
            with open(audit_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    import json
                    entry = json.loads(line)
                    entry_time = entry.get("detected_at", "")
                    # If no last_session_marker, include all entries
                    # Otherwise only include entries after last session
                    if last_session_marker is None or entry_time >= last_session_marker:
                        audit_violations.append(entry)
        except Exception:
            pass
    
    # Clear the audit log after checking (prevents duplicate alerts)
    if audit_violations:
        try:
            audit_log_path.unlink()
        except Exception:
            pass
    
    # Combine violations from both sources
    has_violations = bool(git_violations or audit_violations)
    
    if has_violations:
        details = []
        if git_violations:
            details.extend(git_violations[:3])
        if audit_violations:
            for v in audit_violations[:3]:
                details.append(f"{v.get('type', '?')}: {v.get('path', '?')} (via audit log)")
        
        message_parts = []
        if git_violations:
            message_parts.append(f"git: {len(git_violations)} commit(s)")
        if audit_violations:
            message_parts.append(f"audit log: {len(audit_violations)} access attempt(s)")
        
        return CheckResult(
            rule="MEM-1",
            status="CRITICAL",
            message=f"Direct access to archive-cold/ detected ({', '.join(message_parts)})",
            suggestion="archive-cold/ is read-only for agents. Use archive-query MCP tool to read. Use memory_rotator.py to write.",
            details=details
        )
    
    return CheckResult(rule="MEM-1", status="OK", message="No direct access to archive-cold/ detected")


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
    """DEP-3: Check for non-Orchestrator commits during DEPENDENCY_BLOCKED state.
    
    GAP-9 FIX: Now also checks git author email patterns to detect agent commits.
    Previously only used commit message keyword heuristics which could miss agent work.
    """
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
    
    # GAP-9 FIX: Check author email patterns in recent commits
    # Agent commits are typically identifiable by email patterns like agent@, bot@, ai@, roo@, cline@
    stdout_author, rc_author = run_git(["log", "-5", "--format=%ae"])
    stdout_msg, rc_msg = run_git(["log", "-5", "--format=%s"])
    
    suspicious = []
    agent_commits = []
    
    if rc_author == 0 and stdout_author:
        authors = stdout_author.split("\n")
        messages = stdout_msg.split("\n") if rc_msg == 0 and stdout_msg else []
        
        # Common agent email patterns
        agent_patterns = ["agent@", "bot@", "ai@", "roo@", "cline@", "workbench@"]
        
        for i, author in enumerate(authors):
            if any(pattern in author.lower() for pattern in agent_patterns):
                # Found an agent commit - check if it's a legitimate orchestrator commit
                msg = messages[i] if i < len(messages) else ""
                is_orchestrator = any(keyword in msg.lower() for keyword in ["chore", "docs", "monitor", "dependency", "handoff"])
                
                if not is_orchestrator:
                    agent_commits.append(f"{author}: {msg}")
                    suspicious.append(msg)
    
    # Check commit messages for non-Orchestrator work (original heuristic)
    if rc_msg == 0 and stdout_msg:
        commits = stdout_msg.split("\n")
        msg_suspicious = [c for c in commits if c.strip() and not any(
            keyword in c.lower() for keyword in ["chore", "docs", "monitor", "dependency", "handoff"]
        )]
        # Merge with agent-based detection
        for s in msg_suspicious:
            if s not in suspicious:
                suspicious.append(s)
    
    if suspicious or agent_commits:
        details = agent_commits[:3] if agent_commits else suspicious[:3]
        return CheckResult(
            rule="DEP-3",
            status="CRITICAL",
            message=f"Non-Orchestrator commits detected during DEPENDENCY_BLOCKED state",
            suggestion="Only the Orchestrator Agent may act during DEPENDENCY_BLOCKED. Revert non-Orchestrator commits.",
            details=details
        )
    
    return CheckResult(rule="DEP-3", status="WARNING", message="DEPENDENCY_BLOCKED — only Orchestrator Agent should be active",
                      suggestion="Monitor dependency states and report to human via Roo Chat")


def check_dependency_gate() -> CheckResult:
    """DEP-1: Block src/ commits when dependencies are not MERGED.
    
    GAP-DEP1 FIX: Enforces dependency gate at commit time.
    Before committing src/ changes (Stage 3 work), verifies that all
    dependencies in active_req_id's depends_on list have state = MERGED.
    If any dependency is not MERGED, blocks the commit with CRITICAL.
    """
    state = load_state()
    if not state:
        return CheckResult(rule="DEP-1", status="INFO", message="No state.json found")

    # Check if there are staged src/ changes
    stdout, rc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if rc != 0 or not stdout:
        return CheckResult(rule="DEP-1", status="OK", message="No staged files to check")

    staged_files = [f.strip() for f in stdout.split("\n") if f.strip()]
    has_src_changes = any(f.startswith("src/") for f in staged_files)

    if not has_src_changes:
        return CheckResult(rule="DEP-1", status="OK", message="No src/ changes staged — dependency gate not applicable")

    # Get active_req_id and its dependencies
    active_req_id = state.get("active_req_id")
    if not active_req_id:
        return CheckResult(
            rule="DEP-1",
            status="CRITICAL",
            message="No active_req_id but src/ changes are staged",
            suggestion="Set active_req_id in state.json before committing src/ changes"
        )

    registry = state.get("feature_registry", {})
    active_entry = registry.get(active_req_id, {})
    depends_on = active_entry.get("depends_on", [])

    if not depends_on:
        return CheckResult(rule="DEP-1", status="OK", message=f"active_req_id={active_req_id} has no dependencies")

    # Check each dependency
    non_merged_deps = []
    for dep_id in depends_on:
        dep_entry = registry.get(dep_id, {})
        dep_state = dep_entry.get("state", "UNKNOWN")
        if dep_state != "MERGED":
            non_merged_deps.append(f"{dep_id} (state={dep_state})")

    if non_merged_deps:
        return CheckResult(
            rule="DEP-1",
            status="CRITICAL",
            message=f"Dependencies not MERGED: {non_merged_deps}",
            suggestion="Wait for all dependencies to reach MERGED state before committing src/ changes (Rule DEP-1)",
            details=non_merged_deps
        )

    return CheckResult(rule="DEP-1", status="OK", message=f"All {len(depends_on)} dependencies are MERGED")


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
        # GAP-10 FIX: Stage 4 (Orchestrator/Reviewer/Security) is read-only per FAC-1 table
        # Previously there was a memory-bank/ exception that allowed writes for session management,
        # but per FAC-1, Stage 4 is strictly read-only. Any staged file is a violation.
        if staged_files:
            return CheckResult(
                rule="FAC-1",
                status="CRITICAL",
                message=f"Stage {stage} is read-only but {len(staged_files)} files are staged for write",
                suggestion=f"Unstage all files: git reset HEAD. Stage 4 may not write to any files.",
                details=staged_files[:5]
            )
        return CheckResult(rule="FAC-1", status="OK", message=f"Stage {stage}: no staged files (ok)")
    
    violations = []
    for f in staged_files:
        if not any(f.startswith(prefix) for prefix in allowed_prefixes):
            # Allow memory-bank and docs writes for stages 1-3 (session management exception)
            # GAP-10 FIX: This exception does NOT apply to Stage 4 (handled above)
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


def check_live_imports_ast() -> CheckResult:
    """
    FOR-1(7) + TRC-2: LAACT — Language-specific AST Analysis at Commit Time.
    
    Uses import_analyzer.py to detect live imports from non-MERGED features:
    - Python: Uses Python AST parsing for accurate import detection
    - JavaScript/TypeScript: Uses regex pattern matching
    
    This check runs on staged src/ files to catch violations BEFORE commit.
    Returns CRITICAL if any imports from non-MERGED features are detected.
    """
    state = load_state()
    if not state:
        return CheckResult(rule="FOR-1(7)", status="INFO", message="No state.json found")
    
    # Check if there are staged src/ changes
    stdout, rc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if rc != 0 or not stdout:
        return CheckResult(rule="FOR-1(7)", status="OK", message="No staged files to check")
    
    staged_files = [f.strip() for f in stdout.split("\n") if f.strip()]
    src_files = [f for f in staged_files if f.startswith("src/")]
    
    if not src_files:
        return CheckResult(rule="FOR-1(7)", status="OK", message="No src/ changes staged")
    
    # Dynamically import import_analyzer to avoid circular dependencies
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from import_analyzer import analyze_staged_imports
        
        violations = analyze_staged_imports(src_files, state, REPO_ROOT)
        
        if violations:
            details = [f"{v['file']}: imports '{v['module']}' from {v['req_id']} (state={v['feature_state']})" 
                       for v in violations[:5]]
            return CheckResult(
                rule="FOR-1(7)",
                status="CRITICAL",
                message=f"Live imports from non-MERGED features detected: {len(violations)} violation(s)",
                suggestion="Use stub interfaces instead of live imports from non-MERGED features (Rule TRC-2, FOR-1(7))",
                details=details
            )
        
        return CheckResult(rule="FOR-1(7)", status="OK", message="No live imports from non-MERGED features detected")
    
    except Exception as e:
        return CheckResult(
            rule="FOR-1(7)",
            status="WARNING",
            message=f"Could not run import analyzer: {e}",
            suggestion="Ensure import_analyzer.py exists and is functional"
        )


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


def check_hooks_installed() -> CheckResult:
    """HOOK-INSTALL: Check if Arbiter hooks are properly installed in .git/hooks/.
    
    GAP-4 FIX: Hooks in .workbench/hooks/ are NOT automatically executed by git.
    Git only executes hooks that are installed in .git/hooks/ directory.
    """
    import stat
    
    repo_root = REPO_ROOT
    git_path = repo_root / ".git"
    
    # Resolve the actual .git directory (handles submodules)
    if git_path.is_file():
        # Submodule: .git is a file with content like "gitdir: ../.git/modules/name"
        content = git_path.read_text(encoding="utf-8").strip()
        if content.startswith("gitdir:"):
            git_dir = content[len("gitdir:"):].strip()
            actual_git_dir = (repo_root / git_dir).resolve()
        else:
            return CheckResult(
                rule="HOOK-INSTALL",
                status="WARNING",
                message=".git file has unexpected format",
                suggestion="Verify git repository structure"
            )
    elif git_path.is_dir():
        actual_git_dir = git_path
    else:
        return CheckResult(
            rule="HOOK-INSTALL",
            status="WARNING",
            message="No .git directory found",
            suggestion="Initialize git repository: git init"
        )
    
    hooks_installed = actual_git_dir / "hooks"
    hooks_source = repo_root / ".workbench" / "hooks"
    
    required_hooks = ["pre-commit", "pre-push", "post-merge", "post-tag"]
    missing_hooks = []
    for hook_name in required_hooks:
        hook_path = hooks_installed / hook_name
        if not hook_path.exists():
            missing_hooks.append(hook_name)
    
    if missing_hooks:
        return CheckResult(
            rule="HOOK-INSTALL",
            status="CRITICAL",
            message=f"Required hooks not installed in .git/hooks/: {missing_hooks}",
            suggestion="Install hooks: cp .workbench/hooks/* .git/hooks/ && chmod +x .git/hooks/*",
            details=missing_hooks
        )
    
    return CheckResult(rule="HOOK-INSTALL", status="OK", message="All required hooks are installed")


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


def check_pipeline_enrollment() -> CheckResult:
    """
    GATEKEEPER: Validate that any active work is properly enrolled in the pipeline.

    This check imports gatekeeper.py and uses its check_enrollment logic.
    CRITICAL if: no active_req_id OR feature not in feature_registry
    WARNING if: feature is in terminal state (MERGED, ABANDONED, DELETED)
    OK if: feature properly enrolled and in active state
    """
    try:
        # Dynamically import gatekeeper to avoid circular dependencies
        gatekeeper_path = Path(__file__).parent / "gatekeeper.py"
        spec = importlib.util.spec_from_file_location("gatekeeper", gatekeeper_path)
        gatekeeper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gatekeeper)

        state = load_state()
        result = gatekeeper.check_enrollment(state)

        return CheckResult(
            rule="GATEKEEPER",
            status=result.level,
            message=result.message,
            suggestion=result.suggestion if result.suggestion else "",
        )
    except Exception as e:
        return CheckResult(
            rule="GATEKEEPER",
            status="WARNING",
            message=f"Gatekeeper check failed with exception: {e}",
            suggestion="Ensure gatekeeper.py exists and is valid",
        )


def check_pivot_signature(keys_dir: Path = None) -> CheckResult:
    """
    PVT-2: Verify that pivot branches have valid Architect cryptographic signature.
    
    Rule PVT-2 states:
    - Only the Architect Agent may initiate a pivot during Stage 1
    - Developer may request pivot but requires human approval
    
    This check (CMS — Cryptographic Mode Signing):
    1. Detects if a pivot/* branch exists
    2. Checks git notes for stored pivot assertion signature
    3. Verifies signature using Architect's Ed25519 public key
    4. Returns CRITICAL if pivot created without valid Architect signature
    
    Git note format:
      git notes --ref=pivot-signature add -m 'architect:<base64_signature>' HEAD
    
    Args:
        keys_dir: Optional Path to keys directory for testing. Defaults to KEYS_DIR.
    
    Returns CRITICAL if pivot branch exists without valid Architect signature.
    """
    state = load_state()
    if not state:
        return CheckResult(rule="PVT-2", status="INFO", message="No state.json found")
    
    # Check if state indicates PIVOT_IN_PROGRESS or PIVOT_APPROVED
    current_state = state.get("state", "")
    if current_state not in ["PIVOT_IN_PROGRESS", "PIVOT_APPROVED"]:
        return CheckResult(rule="PVT-2", status="OK", message="Not in pivot state")
    
    # Get active_req_id and stage
    active_req_id = state.get("active_req_id")
    stage = state.get("stage", 0)
    
    # Check for pivot branches
    stdout, rc = run_git(["branch", "-a", "--format=%(refname:short)"])
    
    if rc != 0 or not stdout:
        return CheckResult(rule="PVT-2", status="INFO", message="Cannot check git branches")
    
    pivot_branches = [
        line.strip() for line in stdout.strip().split("\n")
        if line.strip().startswith("pivot/")
    ]
    
    if not pivot_branches:
        return CheckResult(rule="PVT-2", status="OK", message="No pivot branches found")
    
    # Get the pivot ticket ID from state or infer from branch name
    pivot_ticket_id = active_req_id
    if not pivot_ticket_id:
        # Try to infer from first pivot branch
        branch_name = pivot_branches[0]
        # Extract ticket ID from branch name (e.g., pivot/REQ-042-fix -> REQ-042)
        import re
        match = re.search(r"(REQ-\d+)", branch_name)
        if match:
            pivot_ticket_id = match.group(1)
    
    # Import mode_keys dynamically to avoid circular dependencies
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from mode_keys import ModeSigner
        
        signer = ModeSigner(keys_dir=keys_dir)
        
        # Check if architect keys exist
        if not signer.keys_exist("architect"):
            return CheckResult(
                rule="PVT-2",
                status="WARNING",
                message="Architect mode keys not found — cannot verify CMS signature",
                suggestion="Run: python .workbench/scripts/mode_keys.py generate"
            )
        
        # Verify signature for each pivot branch
        violations = []
        for branch_name in pivot_branches:
            # Get git note containing the signature
            # Note ref: refs/notes/pivot-signature
            note_stdout, note_rc = run_git([
                "notes", "--ref=pivot-signature", "show",
                f"refs/heads/{branch_name}"
            ])
            
            if note_rc != 0 or not note_stdout:
                # No signature note found
                violations.append(f"No signature note found for branch {branch_name}")
                continue
            
            # Parse note: expected format 'architect:<base64_signature>'
            note_content = note_stdout.strip()
            if not note_content.startswith("architect:"):
                violations.append(f"Invalid note format for {branch_name}: missing 'architect:' prefix")
                continue
            
            signature = note_content[len("architect:"):].strip()
            
            # Verify signature
            try:
                is_valid = signer.verify_signature(
                    pivot_ticket_id or "UNKNOWN",
                    branch_name,
                    signature,
                    signing_mode="architect"
                )
                if not is_valid:
                    violations.append(f"Invalid signature for branch {branch_name}")
            except Exception as e:
                violations.append(f"Signature verification failed for {branch_name}: {e}")
        
        if violations:
            return CheckResult(
                rule="PVT-2",
                status="CRITICAL",
                message=f"Pivot signature violation: {len(violations)} issue(s) detected",
                suggestion="Only Architect Agent may create pivot branches. Developer pivots require Architect signature.",
                details=violations[:3]
            )
        
        return CheckResult(rule="PVT-2", status="OK", message="Pivot branch has valid Architect signature")
    
    except ImportError:
        return CheckResult(
            rule="PVT-2",
            status="WARNING",
            message="mode_keys.py not available — falling back to email heuristic",
            suggestion="Install cryptography library and ensure mode_keys.py exists"
        )
    except Exception as e:
        return CheckResult(
            rule="PVT-2",
            status="WARNING",
            message=f"PVT-2 check failed: {e}",
            suggestion="Investigate arbiter_check.py for PVT-2 check"
        )


def check_pivot_mode() -> CheckResult:
    """
    PVT-2 (LEGACY): Verify that pivot branches are initiated by the correct agent mode.
    
    DEPRECATED: This function uses email heuristics which can be bypassed.
    Use check_pivot_signature() instead for cryptographic verification.
    
    This legacy function remains for backward compatibility and is invoked
    when the CMS (mode_keys) infrastructure is not available.
    """
    state = load_state()
    if not state:
        return CheckResult(rule="PVT-2", status="INFO", message="No state.json found")
    
    # Check if state indicates PIVOT_IN_PROGRESS or PIVOT_APPROVED
    current_state = state.get("state", "")
    if current_state not in ["PIVOT_IN_PROGRESS", "PIVOT_APPROVED"]:
        return CheckResult(rule="PVT-2", status="OK", message="Not in pivot state")
    
    # Get active_req_id and stage
    active_req_id = state.get("active_req_id")
    stage = state.get("stage", 0)
    
    # Check git log for pivot branch creation
    # Look for branches created recently that match pivot/* pattern
    stdout, rc = run_git(["branch", "-a", "--format=%(refname:short)%(committerdate:unix)"])
    
    if rc != 0 or not stdout:
        return CheckResult(rule="PVT-2", status="INFO", message="Cannot check git branches")
    
    pivot_branches = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        # Branch format: "name timestamp" (we use --format with committerdate:unix)
        parts = line.split()
        if parts:
            branch_name = parts[0]
            if branch_name.startswith("pivot/"):
                pivot_branches.append(branch_name)
    
    if not pivot_branches:
        return CheckResult(rule="PVT-2", status="OK", message="No pivot branches found")
    
    # Get recent pivot-related commits (last 5 commits on pivot branches)
    stdout_commits, rc_commits = run_git([
        "log", "-5", "--format=%H|%ae|%s", "--first-parent"
    ])
    
    if rc_commits != 0 or not stdout_commits:
        return CheckResult(rule="PVT-2", status="WARNING", message="Cannot check git log for pivot commits")
    
    # Agent email patterns to detect non-human commits
    agent_patterns = ["agent@", "bot@", "ai@", "roo@", "cline@", "workbench@", "gpt@", "claude@"]
    
    # Check for APPROVED-BY-HUMAN in recent commits
    has_approved = "APPROVED-BY-HUMAN" in stdout_commits.upper()
    
    # Parse commits and check for agent authorship without approval
    violations = []
    for line in stdout_commits.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        
        commit_hash, author_email, subject = parts[0], parts[1], parts[2]
        
        # Check if author is an agent
        is_agent = any(pattern in author_email.lower() for pattern in agent_patterns)
        
        if is_agent:
            # Agent-initiated pivot detected
            if stage == 1:
                # Stage 1 pivots must be Architect-initiated
                # If agent is doing it without APPROVED-BY-HUMAN, it's a violation
                if not has_approved:
                    violations.append(
                        f"Agent {author_email} initiated pivot at Stage 1 (Architect required)"
                    )
            else:
                # Non-Stage 1 pivots by Developer require APPROVED-BY-HUMAN
                if not has_approved:
                    violations.append(
                        f"Agent {author_email} initiated pivot without APPROVED-BY-HUMAN"
                    )
    
    if violations:
        return CheckResult(
            rule="PVT-2",
            status="CRITICAL",
            message=f"Pivot mode violation: {len(violations)} issue(s) detected",
            suggestion="Only Architect Agent may initiate Stage 1 pivots. Developer pivots require APPROVED-BY-HUMAN.",
            details=violations[:3]
        )
    
    return CheckResult(rule="PVT-2", status="OK", message="Pivot initiated by correct agent mode")


def check_gate_notifications() -> CheckResult:
    """
    GATE_NOTIFY: Report pending HITL gates to human.

    This check uses gate_notification.py to detect gate-blocking states
    and surface pending human actions. INFO level — not blocking.
    """
    try:
        # Dynamically import gate_notification to avoid circular dependencies
        gate_notification_path = Path(__file__).parent / "gate_notification.py"
        spec = importlib.util.spec_from_file_location("gate_notification", gate_notification_path)
        gate_notification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate_notification)

        state = load_state()
        report = gate_notification.check_gates(state)

        if not report.has_pending_gates():
            return CheckResult(
                rule="GATE_NOTIFY",
                status="OK",
                message="No pending human actions — workflow not blocked at any HITL gate",
            )

        # Summarize pending gates
        summary = report.get_summary()
        human_blocking = summary["human_blocking_gates"]
        total = summary["total_pending"]

        if human_blocking > 0:
            return CheckResult(
                rule="GATE_NOTIFY",
                status="INFO",
                message=f"⚠️ {human_blocking} HITL gate(s) require human action — workflow blocked",
                suggestion=f"Run: python .workbench/scripts/orchestrator_monitor.py status --verbose",
            )
        else:
            return CheckResult(
                rule="GATE_NOTIFY",
                status="INFO",
                message=f"{total} pending gate(s) (Orchestrator monitoring, not human-blocking)",
            )
    except Exception as e:
        return CheckResult(
            rule="GATE_NOTIFY",
            status="INFO",
            message=f"Gate notification check unavailable: {e}",
        )


def check_large_file_warning() -> CheckResult:
    """
    LGF-1: Preventive chunking enforcement — WARNING level, not blocking.

    This check warns agents when staged files exceed 500 lines, providing
    guidance on the mandatory chunking protocol before they attempt large
    file operations that could fail and waste tokens.

    Rule LGF-1 states:
    - Files >500 lines MUST use chunked generation (400-500 line chunks)
    - Chunks must be written to numbered temp files and assembled via pipeline
    - Forbidden: inline addition pattern (Get-Content a) + (Get-Content b)

    This is INFO/WARNING level — it PREVENTS wasted effort by warning early,
    not by blocking commits post-hoc.
    """
    # Check if there are staged files
    stdout, rc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if rc != 0 or not stdout:
        return CheckResult(rule="LGF-1", status="OK", message="No staged files to check")

    staged_files = [f.strip() for f in stdout.split("\n") if f.strip()]

    # Files that are exceptions to chunking requirement
    # (generated by scripts, build tools, etc.)
    exception_patterns = [
        r"node_modules/",
        r"\.min\.(js|css)$",
        r"\.bundle\.(js|ts)$",
        r"dist/",
        r"build/",
        r"\.pyc$/",
        r"__pycache__/",
    ]

    # Check each staged file for line count
    large_files = []
    for f in staged_files:
        # Skip exception patterns
        if any(re.match(p, f) for p in exception_patterns):
            continue

        # Get file extension
        file_path = REPO_ROOT / f
        if not file_path.exists():
            continue

        # Only check text files that could be large
        if file_path.suffix.lower() in [".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".json", ".yml", ".yaml"]:
            try:
                line_count = sum(1 for _ in open(file_path, encoding="utf-8", errors="ignore"))
                if line_count > 500:
                    large_files.append((f, line_count))
            except Exception:
                pass

    if not large_files:
        return CheckResult(rule="LGF-1", status="OK", message="No large files (>500 lines) staged")

    # Format details for warning
    file_details = [f"{path} ({lines} lines)" for path, lines in large_files[:5]]

    return CheckResult(
        rule="LGF-1",
        status="WARNING",
        message=f"{len(large_files)} file(s) exceed 500 lines — chunking recommended",
        suggestion=(
            "LGF-1: Files >500 lines MUST use chunked generation. "
            "Split into 400-500 line chunks → write to _temp_chunk_NN.ext → "
            "assemble via pipeline: Get-Content _temp_chunk_*.ext | Set-Content target.ext -Encoding UTF8. "
            "Do NOT use inline addition: (Get-Content a) + (Get-Content b) is forbidden."
        ),
        details=file_details
    )


def check_phase2_evidence() -> CheckResult:
    """
    FOR-1(4): Check for valid Phase 2 evidence seal.
    
    This check verifies that the current commit has a valid Phase 2 test
    execution evidence seal. Phase 2 seal is required for feature branch
    merge to develop/main.
    
    Returns CRITICAL if feature branch merge attempted without Phase 2 seal.
    """
    import json
    
    # Get the current commit hash
    stdout, rc = run_git(["rev-parse", "--verify", "HEAD"])
    if rc != 0 or not stdout:
        return CheckResult(rule="FOR-1(4)", status="INFO", message="Cannot determine current commit")
    
    commit_hash = stdout.strip()
    
    # Check if seal file exists
    seal_file = TEST_EVIDENCE_SEALS / f"{commit_hash}.seal"
    if not seal_file.exists():
        return CheckResult(
            rule="FOR-1(4)",
            status="CRITICAL",
            message=f"No Phase 2 evidence seal found for commit {commit_hash[:8]}",
            suggestion="Run: python .workbench/scripts/test_orchestrator.py run --scope full --set-state"
        )
    
    # Load and verify seal
    try:
        with open(seal_file, "r", encoding="utf-8") as f:
            seal = json.load(f)
    except Exception as e:
        return CheckResult(
            rule="FOR-1(4)",
            status="CRITICAL",
            message=f"Seal file corrupted: {e}",
            suggestion="Run: python .workbench/scripts/test_orchestrator.py run --scope full --set-state"
        )
    
    # Verify Phase 2 was passed
    if not seal.get("phase2_passed"):
        return CheckResult(
            rule="FOR-1(4)",
            status="CRITICAL",
            message=f"Phase 2 was not run or did not pass for commit {commit_hash[:8]}",
            suggestion="Run: python .workbench/scripts/test_orchestrator.py run --scope full --set-state"
        )
    
    return CheckResult(
        rule="FOR-1(4)",
        status="OK",
        message=f"Phase 2 evidence seal valid for commit {commit_hash[:8]}"
    )


def check_state_transition_signature() -> CheckResult:
    """
    FOR-1(1): Check for valid Arbiter-signed state transition.
    
    This check verifies that when state shows GREEN, there is a valid
    Cryptographic State Transition Attribution (CSTA) signature from
    the Arbiter (test_orchestrator). Agents cannot self-sign transitions.
    
    Returns CRITICAL if state shows GREEN but no valid Arbiter signature exists.
    """
    state = load_state()
    if not state:
        return CheckResult(rule="FOR-1(1)", status="INFO", message="No state.json found")
    
    current_state = state.get("state", "")
    
    # Only check if state is GREEN or MERGED (terminal states requiring CSTA)
    if current_state not in ["GREEN", "MERGED"]:
        return CheckResult(rule="FOR-1(1)", status="OK", message=f"State is {current_state} — CSTA check not applicable")
    
    # Get active_req_id for the transition
    active_req_id = state.get("active_req_id")
    if not active_req_id:
        return CheckResult(rule="FOR-1(1)", status="WARNING", message="No active_req_id but state is GREEN — cannot verify CSTA")
    
    # Try to determine the previous state (from_state)
    # Look for a transition signature file with to_state = current state
    # The naming convention is {req_id}_{from}_{to}.sig
    # We need to check if a signature exists for any transition TO GREEN/MERGED
    
    # Check for GREEN transition signature
    if current_state == "GREEN":
        # Look for signatures with to_state = GREEN
        if TEST_EVIDENCE_TRANSITIONS.exists():
            green_sigs = list(TEST_EVIDENCE_TRANSITIONS.glob(f"{active_req_id}_*_GREEN.sig"))
            if green_sigs:
                # Found a signature, verify it
                sig_file = green_sigs[0]
                try:
                    with open(sig_file, "r", encoding="utf-8") as f:
                        sig = json.load(f)
                    
                    # Verify it's from Arbiter
                    arbiter_key_id = sig.get("arbiter_key_id", "")
                    if "arbiter" not in arbiter_key_id.lower():
                        return CheckResult(
                            rule="FOR-1(1)",
                            status="CRITICAL",
                            message=f"State is GREEN but signature is not from Arbiter",
                            suggestion="Only test_orchestrator.py (Arbiter) may sign state transitions"
                        )
                    
                    # Verify signature is valid (not tampered)
                    # Import test_evidence to verify
                    import sys
                    sys.path.insert(0, str(Path(__file__).parent))
                    from test_evidence import _verify, _get_secret_key
                    
                    data = {
                        "from_state": sig.get("from_state"),
                        "to_state": sig.get("to_state"),
                        "req_id": sig.get("req_id"),
                        "timestamp": sig.get("timestamp"),
                        "arbiter_key_id": sig.get("arbiter_key_id"),
                    }
                    signature = sig.get("signature", "")
                    
                    if not _verify(data, signature):
                        return CheckResult(
                            rule="FOR-1(1)",
                            status="CRITICAL",
                            message="State transition signature is invalid or tampered",
                            suggestion="Re-run test_orchestrator.py with --set-state to re-sign the transition"
                        )
                    
                    return CheckResult(
                        rule="FOR-1(1)",
                        status="OK",
                        message=f"Valid Arbiter CSTA signature found for {active_req_id} transition to GREEN"
                    )
                except Exception as e:
                    return CheckResult(
                        rule="FOR-1(1)",
                        status="CRITICAL",
                        message=f"State is GREEN but signature verification failed: {e}",
                        suggestion="Re-run test_orchestrator.py with --set-state to re-sign the transition"
                    )
        
        # No signature found
        return CheckResult(
            rule="FOR-1(1)",
            status="CRITICAL",
            message=f"State is GREEN but no valid Arbiter CSTA signature found for {active_req_id}",
            suggestion="Only test_orchestrator.py (Arbiter) may sign state transitions to GREEN. Agent self-transition is forbidden."
        )
    
    return CheckResult(rule="FOR-1(1)", status="OK", message=f"State is {current_state}")


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
    "DEP-1":          check_dependency_gate,
    "DEP-3":          check_dependency_blocked_mode,
    "FAC-1":          check_file_access_constraints,
    "FOR-1(7)":       check_live_imports_ast,
    "TRC-2":          check_live_imports_ast,
    "REG-1":          check_regression_failures_populated,
    "CMD-TRANSITION": check_arbiter_capabilities_registered,
    "FOR-1":          check_forbidden_self_declaration,
    "FOR-1(1)":       check_state_transition_signature,
    "FOR-1(4)":       check_phase2_evidence,
    "HOOK-INSTALL":   check_hooks_installed,
    "GATEKEEPER":     check_pipeline_enrollment,
    "GATE_NOTIFY":    check_gate_notifications,
    "PVT-2":          check_pivot_signature,
    "LGF-1":          check_large_file_warning,
}

# Checks run in check-session mode (lightweight — 5 critical rules for session startup)
# NOTE: SESSION_CHECKS includes CR-1 which is WARNING level (stale checkpoint detection)
#       SLC-2, MEM-1, MEM-3a, DEP-1, DEP-3, FAC-1, HOOK-INSTALL, GATEKEEPER are CRITICAL level
#       GATE_NOTIFY is INFO level — informational only, not blocking
#       LGF-1 is WARNING level — preventive chunking guidance, not blocking
#       FOR-1(4) is CRITICAL level — Phase 2 evidence enforcement
#       FOR-1(1) is CRITICAL level — CSTA state transition signing
#       FOR-1(7) is CRITICAL level — LAACT live import detection at commit time
SESSION_CHECKS = ["SLC-2", "MEM-1", "MEM-3a", "DEP-1", "DEP-3", "FAC-1", "CR-1", "HOOK-INSTALL", "GATEKEEPER", "GATE_NOTIFY", "LGF-1", "FOR-1(4)", "FOR-1(1)", "FOR-1(7)", "PVT-2"]


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
            # Always show CRITICAL, WARNING, and GATE_NOTIFY INFO results
            if result.status in ["CRITICAL", "WARNING"]:
                print(format_result(result))
                print()
            elif result.status == "INFO" and result.rule == "GATE_NOTIFY":
                # GATE_NOTIFY INFO level is informational — show to human
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
