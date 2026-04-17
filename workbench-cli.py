#!/usr/bin/env python3
"""
workbench-cli.py â€” Agentic Workbench v2.1 Bootstrapper

Owner: The Workbench (Layer 3)
Version: 2.1
Location: Root of agentic-workbench-engine (global install via pip or PATH)

Commands:
  workbench-cli.py init <project-name>     â€” Initialize new application repo with workbench scaffold
  workbench-cli.py upgrade --version <vX.Y> â€” Upgrade existing repo to new workbench version
  workbench-cli.py status                  â€” Display state.json in human-readable format
  workbench-cli.py rotate                  â€” Trigger memory_rotator.py for sprint end

This script is the deterministic bootstrapper. It is NOT bundled in the application repo â€”
it lives globally and injects the workbench engine into new or existing application repos.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

TEMPLATE_REPO = Path(__file__).parent  # The directory containing this script
TEMPLATE_VERSION_FILE = TEMPLATE_REPO / ".workbench-version"

# Files owned by the Workbench (overwritten on upgrade)
ENGINE_FILES = [
    ".clinerules",
    ".roomodes",
    ".roo-settings.json",
    ".workbench-version",
    "biome.json",
]

# Directories owned by the Workbench (overwritten on upgrade)
ENGINE_DIRS = [
    ".workbench/",
]

# Files owned by the Application (never overwritten)
APP_PROTECTED_FILES = [
    "state.json",  # Arbiter-owned, never overwritten
]

# Directories owned by the Application (never overwritten)
APP_PROTECTED_DIRS = [
    "src/",
    "tests/",
    "memory-bank/hot-context/",  # Templates preserved, not overwritten
]


def load_template_version():
    """Read the workbench version from .workbench-version."""
    if not TEMPLATE_VERSION_FILE.exists():
        return "unknown"
    return TEMPLATE_VERSION_FILE.read_text().strip()


def load_state_json(repo_path):
    """Load state.json from a repo path."""
    state_path = repo_path / "state.json"
    if not state_path.exists():
        return None
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_state(repo_path, state):
    """Write state.json atomically."""
    state_path = repo_path / "state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _install_hooks(repo_path):
    """Install Arbiter hooks from .workbench/hooks/ into .git/hooks/.
    
    Handles both regular repos (.git/ is a directory) and git submodules
    (.git is a file containing 'gitdir: <path>').
    """
    import stat
    hooks_src = repo_path / ".workbench" / "hooks"
    
    # Resolve the actual .git directory (handles submodules)
    git_path = repo_path / ".git"
    if git_path.is_file():
        # Submodule: .git is a file with content like "gitdir: ../.git/modules/name"
        content = git_path.read_text(encoding="utf-8").strip()
        if content.startswith("gitdir:"):
            git_dir = content[len("gitdir:"):].strip()
            # Resolve relative path
            actual_git_dir = (repo_path / git_dir).resolve()
        else:
            print(f"  WARNING: .git file has unexpected format — skipping hook installation")
            return
    elif git_path.is_dir():
        actual_git_dir = git_path
    else:
        print(f"  WARNING: No .git found at {git_path} — skipping hook installation")
        return
    
    hooks_dst = actual_git_dir / "hooks"

    if not hooks_src.exists():
        print(f"  WARNING: .workbench/hooks/ not found — skipping hook installation")
        return

    hooks_dst.mkdir(parents=True, exist_ok=True)

    for hook_file in hooks_src.iterdir():
        if hook_file.is_file():
            dst = hooks_dst / hook_file.name
            shutil.copy2(hook_file, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"  Installed hook: {hook_file.name} -> {hooks_dst}/{hook_file.name}")

def cmd_init(project_name):
    """Initialize a new application repo with the workbench scaffold."""
    project_path = Path.cwd() / project_name

    if project_path.exists():
        print(f"ERROR: Directory '{project_name}' already exists", file=sys.stderr)
        sys.exit(1)

    print(f"[WORKBENCH-CLI] Initializing new project: {project_name}")
    print(f"  Template version: {load_template_version()}")

    # Create project directory
    project_path.mkdir(parents=True, exist_ok=True)
    os.chdir(project_path)

    # Run git init
    subprocess.run(["git", "init"], check=True)
    subprocess.run(["git", "branch", "-M", "main"], check=True)

    # Copy engine files from template
    for engine_file in ENGINE_FILES:
        src = TEMPLATE_REPO / engine_file
        dst = project_path / engine_file
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  Copied: {engine_file}")

    # Copy engine directories from template
    for engine_dir in ENGINE_DIRS:
        src = TEMPLATE_REPO / engine_dir
        dst = project_path / engine_dir
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  Copied: {engine_dir}")

    # Copy memory bank hot-context templates (preserve app memory)
    hot_context_src = TEMPLATE_REPO / "memory-bank" / "hot-context"
    hot_context_dst = project_path / "memory-bank" / "hot-context"
    if hot_context_src.exists():
        shutil.copytree(hot_context_src, hot_context_dst, dirs_exist_ok=True)
        print(f"  Copied: memory-bank/hot-context/")

    # Create application-specific directories (empty, with .gitkeep)
    app_dirs = ["src", "tests/unit", "tests/integration", "features", "_inbox", "docs/conversations"]
    for d in app_dirs:
        dir_path = project_path / d
        dir_path.mkdir(parents=True, exist_ok=True)
        gitkeep = dir_path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Create state.json (INIT state)
    state = {
        "version": load_template_version(),
        "state": "INIT",
        "stage": None,
        "active_req_id": None,
        "feature_suite_pass_ratio": None,
        "full_suite_pass_ratio": None,
        "regression_state": "NOT_RUN",
        "regression_failures": [],
        "integration_state": "NOT_RUN",
        "integration_test_pass_ratio": None,
        "feature_registry": {},
        "file_ownership": {},
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "last_updated_by": "workbench-cli",
        "arbiter_capabilities": {
            "test_orchestrator": False,
            "gherkin_validator": False,
            "memory_rotator": False,
            "audit_logger": False,
            "crash_recovery": False,
            "dependency_monitor": False,
            "integration_test_runner": False,
            "git_hooks": False
        }
    }
    state_path = project_path / "state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    print(f"  Created: state.json (INIT)")

    # Initial commit
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore(workbench): initialize Agentic Workbench v" + load_template_version()],
        check=True
    )

    # Install hooks
    _install_hooks(project_path)

    print(f"\n[WORKBENCH-CLI] Project initialized successfully!")
    print(f"  Navigate to: cd {project_name}")
    print(f"  Next: Open in VS Code with Roo Code extension")


def cmd_upgrade(version):
    """Upgrade an existing repo to a new workbench version."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)

    if not state:
        print(f"ERROR: No state.json found. Is this a workbench project?", file=sys.stderr)
        sys.exit(1)

    current_state = state.get("state")
    if current_state not in ["INIT", "MERGED"]:
        print(f"ERROR: Cannot upgrade while state={current_state}. Must be INIT or MERGED.", file=sys.stderr)
        print(f"  Current state: {current_state}", file=sys.stderr)
        sys.exit(1)

    print(f"[WORKBENCH-CLI] Upgrading workbench to version {version}")
    print(f"  Current state: {current_state} (safe to upgrade)")

    # Backup state.json
    state_backup = repo_path / "state.json.bak"
    shutil.copy2(repo_path / "state.json", state_backup)
    print(f"  Backed up: state.json -> state.json.bak")

    # Overwrite engine files
    for engine_file in ENGINE_FILES:
        src = TEMPLATE_REPO / engine_file
        dst = repo_path / engine_file
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  Upgraded: {engine_file}")

    # Overwrite engine directories
    for engine_dir in ENGINE_DIRS:
        src = TEMPLATE_REPO / engine_dir
        dst = repo_path / engine_dir
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  Upgraded: {engine_dir}")

    # Restore state.json (Arbiter-owned, never overwritten)
    shutil.move(state_backup, repo_path / "state.json")
    print(f"  Restored: state.json (Arbiter-owned, unchanged)")

    # Update .workbench-version
    version_file = repo_path / ".workbench-version"
    version_file.write_text(version + "\n", encoding="utf-8")
    print(f"  Updated: .workbench-version = {version}")

    # Git commit (skip pre-commit hook - upgrade is an internal workbench operation)
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "commit", "--no-verify", "-m", f"chore(workbench): upgrade engine to {version}"],
        check=True
    )

    # Install hooks
    _install_hooks(repo_path)

    print(f"\n[WORKBENCH-CLI] Upgrade complete!")


def cmd_status():
    """Display state.json in human-readable format."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)

    if not state:
        print(f"ERROR: No state.json found. Is this a workbench project?", file=sys.stderr)
        sys.exit(1)

    print(f"[WORKBENCH-CLI] Status Report")
    print(f"  Version: {state.get('version', 'unknown')}")
    print(f"  State: {state.get('state')}")
    print(f"  Stage: {state.get('stage')}")
    print(f"  Active REQ: {state.get('active_req_id')}")
    print()
    print(f"  Test Results:")
    print(f"    Feature Suite: {state.get('feature_suite_pass_ratio')}")
    print(f"    Full Suite: {state.get('full_suite_pass_ratio')}")
    print(f"    Regression: {state.get('regression_state')}")
    print()
    print(f"  Integration:")
    print(f"    State: {state.get('integration_state')}")
    print(f"    Pass Ratio: {state.get('integration_test_pass_ratio')}")
    print()
    print(f"  Arbiter Capabilities:")
    for cap, enabled in state.get("arbiter_capabilities", {}).items():
        status = "enabled" if enabled else "disabled"
        print(f"    {cap}: {status}")
    print()
    print(f"  Feature Registry: {len(state.get('feature_registry', {}))} features")
    print(f"  File Ownership: {len(state.get('file_ownership', {}))} files tracked")
    print()
    print(f"  Last Updated: {state.get('last_updated')}")
    print(f"  Last Updated By: {state.get('last_updated_by')}")

    # Run compliance health scan
    check_script = repo_path / ".workbench" / "scripts" / "arbiter_check.py"
    if check_script.exists():
        print()
        subprocess.run(["python3", str(check_script), "check"], cwd=repo_path)


def cmd_rotate():
    """Trigger memory_rotator.py for sprint end."""
    repo_path = Path.cwd()
    rotator_script = repo_path / ".workbench" / "scripts" / "memory_rotator.py"

    if not rotator_script.exists():
        print(f"ERROR: memory_rotator.py not found at {rotator_script}", file=sys.stderr)
        print(f"  Is Layer 2 (Arbiter) installed?", file=sys.stderr)
        sys.exit(1)

    print(f"[WORKBENCH-CLI] Running memory rotator...")
    result = subprocess.run(["python3", str(rotator_script), "rotate"], cwd=repo_path)
    sys.exit(result.returncode)


def cmd_install_hooks():
    """(Re)install Arbiter hooks into .git/hooks/."""
    repo_path = Path.cwd()
    if not (repo_path / ".git").exists():
        print("ERROR: Not a git repository", file=sys.stderr)
        sys.exit(1)
    print(f"[WORKBENCH-CLI] Installing hooks...")
    _install_hooks(repo_path)
    print(f"[WORKBENCH-CLI] Hook installation complete.")


def cmd_start_feature(req_id, slug=None):
    """Transition INIT/MERGED â†’ STAGE_1_ACTIVE and register the feature."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    current_state = state.get("state")
    if current_state not in ["INIT", "MERGED"]:
        print(f"ERROR: Cannot start feature â€” state is {current_state} (expected INIT or MERGED)", file=sys.stderr)
        sys.exit(1)
    registry = state.get("feature_registry", {})
    branch_slug = slug or req_id.lower()
    registry[req_id] = {
        "state": "STAGE_1_ACTIVE",
        "branch": f"feature/S1/{req_id}-{branch_slug}" if slug else f"feature/S1/{req_id}",
        "depends_on": [],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    state["state"] = "STAGE_1_ACTIVE"
    state["stage"] = 1
    state["active_req_id"] = req_id
    state["feature_registry"] = registry
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)
    print(f"[WORKBENCH-CLI] Feature {req_id} started â€” state = STAGE_1_ACTIVE")
    print(f"  Next: Author .feature file, then run: workbench-cli.py lock-requirements --req-id {req_id}")


def cmd_lock_requirements(req_id):
    """Transition STAGE_1_ACTIVE â†’ REQUIREMENTS_LOCKED after HITL 1 approval."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    current_state = state.get("state")
    if current_state != "STAGE_1_ACTIVE":
        print(f"ERROR: Cannot lock requirements â€” state is {current_state} (expected STAGE_1_ACTIVE)", file=sys.stderr)
        sys.exit(1)
    features_dir = repo_path / "features"
    feature_files = list(features_dir.glob(f"{req_id}-*.feature"))
    if not feature_files:
        print(f"ERROR: No .feature file found for {req_id} in /features/", file=sys.stderr)
        sys.exit(1)
    validator = repo_path / ".workbench" / "scripts" / "gherkin_validator.py"
    if validator.exists():
        result = subprocess.run(
            ["python3", str(validator), str(features_dir)],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR: Gherkin validation failed for {req_id}", file=sys.stderr)
            print(result.stdout)
            sys.exit(1)
    registry = state.get("feature_registry", {})
    feature_entry = registry.get(req_id, {})
    depends_on = feature_entry.get("depends_on", [])
    unmet_deps = [dep for dep in depends_on if registry.get(dep, {}).get("state") != "MERGED"]
    if unmet_deps:
        state["state"] = "DEPENDENCY_BLOCKED"
        registry[req_id]["state"] = "DEPENDENCY_BLOCKED"
        print(f"[WORKBENCH-CLI] {req_id} DEPENDENCY_BLOCKED â€” unmet: {unmet_deps}")
    else:
        state["state"] = "REQUIREMENTS_LOCKED"
        state["stage"] = 2
        registry[req_id]["state"] = "REQUIREMENTS_LOCKED"
        print(f"[WORKBENCH-CLI] Requirements locked â€” state = REQUIREMENTS_LOCKED")
        print(f"  Next: Test Engineer Agent writes failing tests, then run: workbench-cli.py set-red --req-id {req_id}")
    state["feature_registry"] = registry
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)


def cmd_set_red(req_id):
    """Transition REQUIREMENTS_LOCKED â†’ RED after Test Engineer confirms failing tests."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    current_state = state.get("state")
    if current_state != "REQUIREMENTS_LOCKED":
        print(f"ERROR: Cannot set RED â€” state is {current_state} (expected REQUIREMENTS_LOCKED)", file=sys.stderr)
        sys.exit(1)
    state["state"] = "RED"
    state["stage"] = 3
    registry = state.get("feature_registry", {})
    if req_id in registry:
        registry[req_id]["state"] = "RED"
    state["feature_registry"] = registry
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)
    print(f"[WORKBENCH-CLI] {req_id} â€” state = RED. Developer Agent may now begin Stage 3.")


def cmd_review_pending(req_id):
    """Transition GREEN â†’ REVIEW_PENDING after integration tests pass."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    current_state = state.get("state")
    if current_state != "GREEN":
        print(f"ERROR: Cannot set REVIEW_PENDING â€” state is {current_state} (expected GREEN)", file=sys.stderr)
        sys.exit(1)
    integration_state = state.get("integration_state")
    if integration_state != "GREEN":
        print(f"ERROR: Cannot set REVIEW_PENDING â€” integration_state is {integration_state} (expected GREEN)", file=sys.stderr)
        print(f"  Run: python .workbench/scripts/integration_test_runner.py run --set-state", file=sys.stderr)
        sys.exit(1)
    state["state"] = "REVIEW_PENDING"
    state["stage"] = 4
    registry = state.get("feature_registry", {})
    if req_id in registry:
        registry[req_id]["state"] = "REVIEW_PENDING"
    state["feature_registry"] = registry
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)
    print(f"[WORKBENCH-CLI] {req_id} â€” state = REVIEW_PENDING. Awaiting HITL 2 approval.")
    print(f"  Next: Lead Engineer reviews PR, then run: workbench-cli.py merge --req-id {req_id}")


def cmd_merge(req_id):
    """Mark a feature as MERGED and close the pipeline cycle."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    current_state = state.get("state")
    if current_state != "REVIEW_PENDING":
        print(f"ERROR: Cannot merge â€” state is {current_state} (expected REVIEW_PENDING)", file=sys.stderr)
        sys.exit(1)
    registry = state.get("feature_registry", {})
    if req_id not in registry:
        print(f"ERROR: {req_id} not found in feature_registry", file=sys.stderr)
        sys.exit(1)
    registry[req_id]["state"] = "MERGED"
    registry[req_id]["merged_at"] = datetime.now(timezone.utc).isoformat()
    state["state"] = "MERGED"
    state["active_req_id"] = None
    state["stage"] = None
    state["feature_registry"] = registry
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)
    print(f"[WORKBENCH-CLI] Feature {req_id} MERGED")
    monitor_script = repo_path / ".workbench" / "scripts" / "dependency_monitor.py"
    if monitor_script.exists():
        subprocess.run(["python3", str(monitor_script), "check-unblock"], cwd=repo_path)
    print(f"\n[WORKBENCH-CLI] Pipeline cycle complete. Ready for next feature.")


def cmd_check():
    """Run Arbiter compliance health scan."""
    repo_path = Path.cwd()
    check_script = repo_path / ".workbench" / "scripts" / "arbiter_check.py"
    if not check_script.exists():
        print(f"ERROR: arbiter_check.py not found at {check_script}", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(["python3", str(check_script), "check"], cwd=repo_path)
    sys.exit(result.returncode)


def cmd_register_arbiter():
    """GAP-4: Register all Arbiter script capabilities in state.json."""
    repo_path = Path.cwd()
    state = load_state_json(repo_path)
    if not state:
        print("ERROR: No state.json found.", file=sys.stderr)
        sys.exit(1)
    
    scripts_dir = repo_path / ".workbench" / "scripts"
    
    # Capability key mapping
    capabilities = {
        "test_orchestrator": "test_orchestrator.py",
        "gherkin_validator": "gherkin_validator.py",
        "memory_rotator": "memory_rotator.py",
        "audit_logger": "audit_logger.py",
        "crash_recovery": "crash_recovery.py",
        "dependency_monitor": "dependency_monitor.py",
        "integration_test_runner": "integration_test_runner.py",
        "git_hooks": ".git/hooks/pre-commit",
    }
    
    registered = []
    for cap_key, script_name in capabilities.items():
        script_path = scripts_dir / script_name if not script_name.startswith(".git") else repo_path / script_name
        if script_path.exists():
            state["arbiter_capabilities"][cap_key] = True
            registered.append(cap_key)
        else:
            state["arbiter_capabilities"][cap_key] = False
    
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["last_updated_by"] = "workbench-cli"
    _write_state(repo_path, state)
    
    print(f"[WORKBENCH-CLI] Registered {len(registered)} Arbiter capabilities:")
    for cap in registered:
        print(f"  ✓ {cap}")


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Workbench v2.1 CLI â€” Bootstrapper and Lifecycle Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cli-version", action="store_true", help="Print the CLI version and exit")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize new application repo with workbench scaffold")
    init_parser.add_argument("project_name", help="Name of the project directory to create")

    # upgrade command
    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade existing repo to new workbench version")
    upgrade_parser.add_argument("--version", required=True, help="Target version (e.g., v2.1)")

    # status command
    subparsers.add_parser("status", help="Display state.json in human-readable format")

    # rotate command
    subparsers.add_parser("rotate", help="Trigger memory_rotator.py for sprint end")

    # install-hooks command
    subparsers.add_parser("install-hooks", help="(Re)install Arbiter hooks into .git/hooks/")

    # start-feature command
    sf_parser = subparsers.add_parser("start-feature", help="Transition INIT/MERGED â†’ STAGE_1_ACTIVE")
    sf_parser.add_argument("--req-id", required=True, help="Feature requirement ID (e.g., REQ-001)")
    sf_parser.add_argument("--slug", help="Optional branch slug (e.g., user-login)")

    # lock-requirements command
    lr_parser = subparsers.add_parser("lock-requirements", help="Transition STAGE_1_ACTIVE â†’ REQUIREMENTS_LOCKED")
    lr_parser.add_argument("--req-id", required=True, help="Feature requirement ID")

    # set-red command
    sr_parser = subparsers.add_parser("set-red", help="Transition REQUIREMENTS_LOCKED â†’ RED")
    sr_parser.add_argument("--req-id", required=True, help="Feature requirement ID")

    # review-pending command
    rp_parser = subparsers.add_parser("review-pending", help="Transition GREEN â†’ REVIEW_PENDING")
    rp_parser.add_argument("--req-id", required=True, help="Feature requirement ID")

    # merge command
    merge_parser = subparsers.add_parser("merge", help="Mark feature as MERGED, close pipeline cycle")
    merge_parser.add_argument("--req-id", required=True, help="Feature requirement ID")

    # check command
    subparsers.add_parser("check", help="Run Arbiter compliance health scan")

    # register-arbiter command
    subparsers.add_parser("register-arbiter", help="Register all Arbiter script capabilities in state.json")

    args = parser.parse_args()

    if args.cli_version:
        print(f"Agentic Workbench CLI v{load_template_version()}")
        sys.exit(0)

    if args.command == "init":
        cmd_init(args.project_name)
    elif args.command == "upgrade":
        cmd_upgrade(args.version)
    elif args.command == "status":
        cmd_status()
    elif args.command == "rotate":
        cmd_rotate()
    elif args.command == "install-hooks":
        cmd_install_hooks()
    elif args.command == "start-feature":
        cmd_start_feature(args.req_id, args.slug)
    elif args.command == "lock-requirements":
        cmd_lock_requirements(args.req_id)
    elif args.command == "set-red":
        cmd_set_red(args.req_id)
    elif args.command == "review-pending":
        cmd_review_pending(args.req_id)
    elif args.command == "merge":
        cmd_merge(args.req_id)
    elif args.command == "check":
        cmd_check()
    elif args.command == "register-arbiter":
        cmd_register_arbiter()
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
