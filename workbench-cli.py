#!/usr/bin/env python3
"""
workbench-cli.py — Agentic Workbench v2.1 Bootstrapper

Owner: The Workbench (Layer 3)
Version: 2.1
Location: Root of agentic-workbench-template (global install via pip or PATH)

Commands:
  workbench-cli.py init <project-name>     — Initialize new application repo with workbench scaffold
  workbench-cli.py upgrade --version <vX.Y> — Upgrade existing repo to new workbench version
  workbench-cli.py status                  — Display state.json in human-readable format
  workbench-cli.py rotate                  — Trigger memory_rotator.py for sprint end

This script is the deterministic bootstrapper. It is NOT bundled in the application repo —
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

    # Git commit
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"chore(workbench): upgrade engine to v{version}"],
        check=True
    )
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


def cmd_rotate():
    """Trigger memory_rotator.py for sprint end."""
    repo_path = Path.cwd()
    rotator_script = repo_path / ".workbench" / "scripts" / "memory_rotator.py"

    if not rotator_script.exists():
        print(f"ERROR: memory_rotator.py not found at {rotator_script}", file=sys.stderr)
        print(f"  Is Layer 2 (Arbiter) installed?", file=sys.stderr)
        sys.exit(1)

    print(f"[WORKBENCH-CLI] Running memory rotator...")
    result = subprocess.run(["python", str(rotator_script), "rotate"], cwd=repo_path)
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Workbench v2.1 CLI — Bootstrapper and Lifecycle Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
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

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args.project_name)
    elif args.command == "upgrade":
        cmd_upgrade(args.version)
    elif args.command == "status":
        cmd_status()
    elif args.command == "rotate":
        cmd_rotate()
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()