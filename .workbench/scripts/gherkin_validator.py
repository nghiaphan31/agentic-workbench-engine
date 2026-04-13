#!/usr/bin/env python3
"""
gherkin_validator.py — The Arbiter's Gherkin Validator

Owner: The Arbiter (Layer 2)
Version: 2.1
Location: .workbench/scripts/gherkin_validator.py

Validates .feature files for Given/When/Then syntax.
Parses @REQ-NNN and @depends-on: tags.
Cross-references REQ-IDs against state.json.feature_registry.

Usage:
  python gherkin_validator.py features/
  python gherkin_validator.py _inbox/  # @draft files, no REQ-ID requirement
  python gherkin_validator.py --allow-draft _inbox/
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

STATE_JSON_PATH = Path(__file__).parent.parent.parent / "state.json"


def load_state():
    if not STATE_JSON_PATH.exists():
        return None
    with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_feature_file(file_path, require_req_id=True):
    """Validate a single .feature file."""
    errors = []
    warnings = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"valid": False, "errors": [f"Cannot read file: {e}"]}

    lines = content.split("\n")

    # Check for @REQ-NNN tag
    req_id_match = re.search(r"@REQ-(\d+)", content)
    req_id = f"REQ-{req_id_match.group(1).zfill(3)}" if req_id_match else None

    if require_req_id and not req_id:
        errors.append(f"Missing @REQ-NNN tag (e.g., @REQ-001)")

    # Check for @depends-on tags
    depends_on = re.findall(r"@depends-on:\s*(.+?)(?:\n|$)", content)
    depends_on_list = []
    for dep in depends_on:
        # Parse comma-separated REQ-IDs
        ids = re.findall(r"REQ-\d+", dep)
        depends_on_list.extend(ids)

    # Validate @depends-on references
    if req_id and depends_on_list:
        state = load_state()
        if state:
            registry = state.get("feature_registry", {})
            for dep_id in depends_on_list:
                if dep_id not in registry:
                    # Dependency not yet registered — warn only (may be planned)
                    warnings.append(
                        f"@depends-on references {dep_id} but it is not in feature_registry (may be planned)"
                    )
                else:
                    dep_state = registry[dep_id].get("state", "UNKNOWN")
                    if dep_state != "MERGED":
                        # Dependency exists but is not MERGED — this is a blocking error
                        errors.append(
                            f"@depends-on references {dep_id} but its state is '{dep_state}' (must be MERGED before Stage 3)"
                        )

    # Check for Given/When/Then structure
    has_scenario = "Scenario:" in content or "Scenario Outline:" in content
    has_steps = any(keyword in content for keyword in ["Given", "When", "Then", "And", "But"])

    if not has_scenario:
        errors.append("Missing Scenario: or Scenario Outline: declaration")

    if not has_steps:
        errors.append("Missing Given/When/Then/And/But step declarations")

    # Check step structure
    step_pattern = re.compile(r"^\s*(Given|When|Then|And|But)\s+.+", re.MULTILINE)
    steps = step_pattern.findall(content)
    if not steps:
        errors.append("No executable steps found (Given/When/Then/And/But)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "req_id": req_id,
        "depends_on": depends_on_list,
        "steps_count": len(steps)
    }


def validate_directory(dir_path, require_req_id=True):
    """Validate all .feature files in a directory."""
    if not dir_path.exists():
        return {"valid": False, "errors": [f"Directory not found: {dir_path}"]}

    feature_files = list(dir_path.glob("*.feature"))
    if not feature_files:
        return {"valid": True, "message": f"No .feature files found in {dir_path}"}

    results = []
    all_errors = []
    all_warnings = []

    for f in feature_files:
        result = validate_feature_file(f, require_req_id=require_req_id)
        result["file"] = f.name
        results.append(result)

        if not result["valid"]:
            all_errors.append(f"{f.name}: {result['errors']}")
        for w in result.get("warnings", []):
            all_warnings.append(f"{f.name}: {w}")

    return {
        "valid": len(all_errors) == 0,
        "files_checked": len(feature_files),
        "results": results,
        "errors": all_errors,
        "warnings": all_warnings
    }


def main():
    parser = argparse.ArgumentParser(description="The Arbiter's Gherkin Validator")
    parser.add_argument("directory", help="Directory containing .feature files")
    parser.add_argument("--allow-draft", action="store_true", help="Allow @draft files without REQ-ID")

    args = parser.parse_args()

    dir_path = Path(args.directory)
    require_req_id = not args.allow_draft

    result = validate_directory(dir_path, require_req_id=require_req_id)

    print(f"[GHERKIN VALIDATOR] Validating: {dir_path}")
    print(f"  Files Checked: {result.get('files_checked', 0)}")
    print(f"  Valid: {result['valid']}")

    if result.get("errors"):
        print(f"  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")

    if result.get("warnings"):
        print(f"  Warnings:")
        for w in result["warnings"]:
            print(f"    - {w}")

    if result.get("message"):
        print(f"  Note: {result['message']}")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()