#!/usr/bin/env python3
"""
test_orchestrator.py — The Arbiter's Test Orchestrator

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/test_orchestrator.py

Two-phase test execution:
  Phase 1 (Feature Scope Run): --scope feature --req-id REQ-NNN
  Phase 2 (Full Regression Run): --scope full

Exit codes:
  0 = all tests passed
  1 = one or more tests failed
  2 = error (missing req-id, test framework not found, etc.)

Usage:
  python test_orchestrator.py run --scope feature --req-id REQ-001
  python test_orchestrator.py run --scope full
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

STATE_JSON_PATH = Path(__file__).parent.parent.parent / "state.json"
HOT_CONTEXT_PATH = Path(__file__).parent.parent.parent / "memory-bank" / "hot-context"
TESTS_UNIT_PATH = Path(__file__).parent.parent.parent / "tests" / "unit"
TESTS_INTEGRATION_PATH = Path(__file__).parent.parent.parent / "tests" / "integration"


def load_state():
    if not STATE_JSON_PATH.exists():
        return None
    with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def run_tests(test_paths, description):
    """Run a list of test paths and return (exit_code, pass_ratio)."""
    if not test_paths:
        return 0, 1.0  # No tests = pass

    # Check for mock runner environment variable (testing mode)
    mock_runner = os.environ.get("WORKBENCH_MOCK_RUNNER", "")
    if mock_runner == "pass":
        return 0, 1.0
    elif mock_runner == "fail":
        return 1, 0.0

    # Try multiple test runners (language-agnostic)
    exit_code = None
    for runner in ["pytest", "vitest", "jest", "npm test", "pnpm test"]:
        if runner in ["pytest"]:
            result = subprocess.run(
                [runner, "--tb=short", "-v"] + test_paths,
                capture_output=True,
                text=True,
                timeout=300
            )
        elif runner in ["vitest", "jest"]:
            result = subprocess.run(
                ["npx", runner, "--reporter=json", "--outputFile=test-results.json"] + test_paths,
                capture_output=True,
                text=True,
                timeout=300
            )
        elif runner in ["npm test", "pnpm test"]:
            result = subprocess.run(
                runner.split(),
                capture_output=True,
                text=True,
                timeout=300
            )
        else:
            continue

        if result.returncode is not None:
            exit_code = result.returncode
            break

    # Fallback: exit-code-only detection (always runs for language-agnostic)
    if exit_code is None:
        result = subprocess.run(
            ["make", "test"] if os.path.exists("Makefile") else ["echo", "No test runner configured"],
            capture_output=True,
            text=True,
            timeout=300
        )
        exit_code = result.returncode

    return exit_code, 1.0 if exit_code == 0 else 0.0


def write_handoff(req_id, phase, result, pass_ratio, regression_failures):
    """Write structured handoff to handoff-state.md."""
    handoff_path = HOT_CONTEXT_PATH / "handoff-state.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"""
## Test Orchestrator Handoff [{timestamp}]
- **REQ-ID:** {req_id}
- **Phase:** {phase}
- **Result:** {'PASS' if result == 0 else 'FAIL'}
- **Pass Ratio:** {pass_ratio:.1%}
- **Regression Failures:** {len(regression_failures)}
"""

    if regression_failures:
        entry += "- **Failed Tests:**\n"
        for failure in regression_failures:
            entry += f"  - {failure}\n"

    entry += "\n---\n"

    if handoff_path.exists():
        with open(handoff_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# handoff-state.md — Inter-Agent Handoff Message Bus\n\n"

    with open(handoff_path, "w", encoding="utf-8") as f:
        f.write(content + entry)


def run_feature_scope(req_id):
    """Phase 1: Run only the feature's tests (fast inner loop)."""
    pattern = f"{req_id}-*.spec.ts"
    test_paths = list(TESTS_UNIT_PATH.glob(pattern))

    if not test_paths:
        return {
            "exit_code": 0,
            "pass_ratio": 1.0,
            "description": f"No tests found for {req_id} (skipped)"
        }

    exit_code, pass_ratio = run_tests([str(p) for p in test_paths], f"Feature scope: {req_id}")
    return {
        "exit_code": exit_code,
        "pass_ratio": pass_ratio,
        "description": f"Feature scope: {req_id}"
    }


def run_full_regression():
    """Phase 2: Run ALL unit tests + ALL integration tests."""
    unit_tests = list(TESTS_UNIT_PATH.glob("**/*.spec.ts"))
    integration_tests = list(TESTS_INTEGRATION_PATH.glob("**/*.integration.spec.ts"))
    all_tests = [str(p) for p in unit_tests + integration_tests]

    exit_code, pass_ratio = run_tests(all_tests, "Full regression suite")
    return {
        "exit_code": exit_code,
        "pass_ratio": pass_ratio,
        "description": "Full regression suite"
    }


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Test Orchestrator")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    run_parser = subparsers.add_parser("run", help="Run test suite")
    run_parser.add_argument("--scope", choices=["feature", "full"], required=True, help="Test scope")
    run_parser.add_argument("--req-id", help="REQ-ID for feature scope (e.g., REQ-001)")
    run_parser.add_argument("--set-state", action="store_true", help="Update state.json with results")

    args = parser.parse_args()

    if args.command == "run":
        if args.scope == "feature" and not args.req_id:
            print("ERROR: --req-id required for --scope feature", file=sys.stderr)
            sys.exit(2)

        state = load_state()
        if not state:
            print("ERROR: state.json not found", file=sys.stderr)
            sys.exit(2)

        if args.scope == "feature":
            result = run_feature_scope(args.req_id)
            phase = "Phase 1 — Feature Scope Run"
            pass_ratio = result["pass_ratio"]

            if args.set_state:
                if pass_ratio == 1.0:
                    state["state"] = "FEATURE_GREEN"
                    state["feature_suite_pass_ratio"] = pass_ratio
                else:
                    state["state"] = "RED"
                    state["feature_suite_pass_ratio"] = pass_ratio
                state["last_updated"] = datetime.now(timezone.utc).isoformat()
                state["last_updated_by"] = "test_orchestrator.py"
                save_state(state)

            write_handoff(args.req_id, phase, result["exit_code"], pass_ratio, [])

            print(f"[TEST ORCHESTRATOR] {phase}")
            print(f"  REQ-ID: {args.req_id}")
            print(f"  Pass Ratio: {pass_ratio:.1%}")
            print(f"  Exit Code: {result['exit_code']}")

        elif args.scope == "full":
            result = run_full_regression()
            phase = "Phase 2 — Full Regression Run"
            pass_ratio = result["pass_ratio"]

            if args.set_state:
                if pass_ratio == 1.0:
                    state["state"] = "GREEN"
                    state["regression_state"] = "CLEAN"
                else:
                    state["state"] = "REGRESSION_RED"
                    state["regression_state"] = "REGRESSION_RED"
                    state["regression_failures"] = []  # TODO: parse from test output
                state["full_suite_pass_ratio"] = pass_ratio
                state["last_updated"] = datetime.now(timezone.utc).isoformat()
                state["last_updated_by"] = "test_orchestrator.py"
                save_state(state)

            write_handoff(state.get("active_req_id", "ALL"), phase, result["exit_code"], pass_ratio, state.get("regression_failures", []))

            print(f"[TEST ORCHESTRATOR] {phase}")
            print(f"  Active REQ: {state.get('active_req_id', 'N/A')}")
            print(f"  Pass Ratio: {pass_ratio:.1%}")
            print(f"  Exit Code: {result['exit_code']}")

        sys.exit(result["exit_code"])

    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()