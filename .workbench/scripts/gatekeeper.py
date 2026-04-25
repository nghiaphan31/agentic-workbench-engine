#!/usr/bin/env python3
"""
gatekeeper.py — Pipeline Enrollment Validator

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/gatekeeper.py

Validates that any active work is properly enrolled in the pipeline:
- Has a valid active_req_id in state.json
- That req_id exists in feature_registry
- The feature is not in a terminal state

Run during SCAN step (SLC-1 step 0) of startup protocol.

Usage:
  python gatekeeper.py check-enrollment          # Full check, exit 0/1
  python gatekeeper.py check-enrollment --verbose # Human-readable output
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
STATE_JSON = REPO_ROOT / "state.json"
HOT_CONTEXT = REPO_ROOT / "memory-bank" / "hot-context"

TERMINAL_STATES = ["MERGED", "ABANDONED", "DELETED"]

GATEWAY_STATES = [
    "STAGE_1_ACTIVE",
    "REQUIREMENTS_LOCKED",
    "DEPENDENCY_BLOCKED",
    "RED",
    "FEATURE_GREEN",
    "REGRESSION_RED",
    "GREEN",
    "INTEGRATION_CHECK",
    "INTEGRATION_RED",
    "REVIEW_PENDING",
    "PIVOT_IN_PROGRESS",
    "PIVOT_APPROVED",
    "UPGRADE_IN_PROGRESS",
]


@dataclass
class EnrollmentResult:
    level: str  # CRITICAL, WARNING, INFO, OK
    message: str
    suggestion: str = ""
    req_id: str = ""


def load_state() -> dict:
    """Load state.json, return empty dict if missing."""
    if not STATE_JSON.exists():
        return {}
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def check_enrollment(state: dict) -> EnrollmentResult:
    """
    Check if the current session is working on a properly enrolled feature.

    Returns:
        EnrollmentResult with level and message
    """
    # Case 1: No active_req_id — no feature in progress
    active_req_id = state.get("active_req_id")
    if not active_req_id:
        return EnrollmentResult(
            level="CRITICAL",
            message=(
                "No active feature in progress. "
                "All new work must be enrolled via Stage 1 (Architect Agent) before implementation begins. "
                "Hint: Create a .feature file with @REQ-NNN tag, get HITL Gate 1 approval, "
                "then the feature will be registered in state.json.feature_registry."
            ),
            suggestion="Run: workbench-cli.py init-feature (or manually enroll via Architect Agent → Stage 1)",
        )

    # Case 2: active_req_id is set but feature_registry is empty or doesn't contain it
    feature_registry = state.get("feature_registry", {})
    if not feature_registry:
        return EnrollmentResult(
            level="CRITICAL",
            message=(
                f"active_req_id is '{active_req_id}' but feature_registry is empty. "
                f"This feature has not been enrolled through the pipeline. "
                f"Implementation work cannot begin without Stage 1 completion."
            ),
            suggestion=(
                f"Halt current work on {active_req_id}. "
                f"Return to Architect Agent to create the .feature file and complete HITL Gate 1."
            ),
            req_id=str(active_req_id),
        )

    if active_req_id not in feature_registry:
        return EnrollmentResult(
            level="CRITICAL",
            message=(
                f"active_req_id is '{active_req_id}' but this feature is not in state.json.feature_registry. "
                f"Feature must be registered through the pipeline before implementation work begins."
            ),
            suggestion=(
                f"Halt current work on {active_req_id}. "
                f"Complete Stage 1: Architect Agent creates .feature file, HITL Gate 1 approval, "
                f"then feature will appear in feature_registry with state REQUIREMENTS_LOCKED."
            ),
            req_id=str(active_req_id),
        )

    # Case 3: Feature is in a terminal state
    feature_entry = feature_registry.get(active_req_id, {})
    feature_state = feature_entry.get("state", "UNKNOWN")

    if feature_state in TERMINAL_STATES:
        return EnrollmentResult(
            level="WARNING",
            message=(
                f"active_req_id is '{active_req_id}' which is in terminal state '{feature_state}'. "
                f"No active work should be in progress on this feature."
            ),
            suggestion=(
                f"Feature {active_req_id} has reached {feature_state}. "
                f"Next feature cycle should be started for new work. "
                f"Current session may be stale — restart recommended."
            ),
            req_id=str(active_req_id),
        )

    # Case 4: Feature is in a valid active state
    return EnrollmentResult(
        level="OK",
        message=f"Feature '{active_req_id}' is properly enrolled (state: {feature_state})",
        req_id=str(active_req_id),
    )


def format_result(result: EnrollmentResult, verbose: bool = False) -> str:
    """Format enrollment result for human-readable output."""
    icon = {
        "CRITICAL": "🚨",
        "WARNING": "⚠️",
        "INFO": "ℹ️",
        "OK": "✅",
    }.get(result.level, "?")

    lines = [
        f"{icon} [{result.level}] {result.message}",
    ]

    if result.suggestion:
        lines.append(f"   → {result.suggestion}")

    if verbose and result.req_id:
        lines.append(f"   Feature: {result.req_id}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline Enrollment Validator")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Human-readable verbose output"
    )
    args = parser.parse_args()

    state = load_state()
    result = check_enrollment(state)

    if args.verbose or True:  # Always verbose for now
        print(format_result(result, verbose=True))

    # Exit codes: 0 = OK/WARNING can proceed, 1 = CRITICAL must halt
    if result.level == "CRITICAL":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()