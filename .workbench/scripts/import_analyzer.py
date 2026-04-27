#!/usr/bin/env python3
"""
import_analyzer.py — Language-specific AST Analysis at Commit Time (LAACT)

Owner: The Arbiter (Layer 2)
Version: 2.2
Location: .workbench/scripts/import_analyzer.py

Detects imports from non-MERGED features using language-specific analysis:
- Python: Uses AST parsing for accurate import detection
- JavaScript/TypeScript: Uses regex pattern matching (no full parser)

This module is used by arbiter_check.py and the pre-commit hook to enforce
FOR-1(7) and TRC-2: Live Import Detection.

Usage:
  from import_analyzer import analyze_staged_imports, check_live_imports
  violations = analyze_staged_imports(staged_files, state_json_path)
"""

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
STATE_JSON = REPO_ROOT / "state.json"


def load_state() -> Optional[dict]:
    """Load state.json if it exists."""
    if not STATE_JSON.exists():
        return None
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_merged_features(state: dict) -> set:
    """Extract set of MERGED feature req_ids from feature_registry."""
    if not state:
        return set()
    registry = state.get("feature_registry", {})
    return {req_id for req_id, entry in registry.items() if entry.get("state") == "MERGED"}


def get_feature_slug_from_path(module_path: str, registry: dict) -> Optional[str]:
    """
    Extract feature slug from a module path and find the corresponding req_id.
    
    Args:
        module_path: e.g., "features.payment_checkout.service" or "@/features/auth/api"
        registry: feature_registry from state.json
    
    Returns:
        The req_id (e.g., "REQ-042") if found, None otherwise
    """
    # Normalize path
    normalized = module_path.lower().replace("-", "_").replace("/", ".")
    
    # Pattern: features.{slug}.* or @/features/{slug}/*
    # Extract slug between features/ and next path component
    slug_pattern = re.compile(
        r"(?:features[./]|@[/]?features[./])([a-z_]+)",
        re.IGNORECASE
    )
    match = slug_pattern.search(normalized)
    if not match:
        return None
    
    slug = match.group(1)
    
    # Find req_id with matching branch slug
    for req_id, entry in registry.items():
        branch = entry.get("branch", "")
        if not branch:
            continue
        # branch format: feature/REQ-XXX-slug or lab/REQ-XXX-slug
        # Extract slug portion (part after REQ-XXX-)
        branch_slug = branch.split("/")[-1].lower().replace("-", "_") if branch else ""
        
        # Remove the req_id prefix (e.g., "req_038_") to get the actual slug
        # The branch format is feature/REQ-XXX-slug or lab/REQ-XXX-slug
        # We want to extract "slug" from "req_038_slug"
        parts = branch_slug.split("_")
        
        # Find first numeric part (the req number) and take everything after it
        # e.g., ["req", "038", "payment"] -> ["payment"]
        # e.g., ["req", "038", "payment", "checkout"] -> ["payment", "checkout"]
        numeric_idx = None
        for i, part in enumerate(parts):
            if part.isdigit():
                numeric_idx = i
                break
        
        if numeric_idx is not None and numeric_idx + 1 < len(parts):
            actual_slug_parts = parts[numeric_idx + 1:]
            # Check if slug matches any suffix of the branch slug
            for i in range(len(actual_slug_parts)):
                suffix = "_".join(actual_slug_parts[i:])
                if suffix == slug:
                    return req_id
            # Also check if slug is a single part
            if slug in actual_slug_parts:
                return req_id
        elif branch_slug == slug:
            return req_id
    
    return None


def analyze_python_imports(staged_files: list, state: dict = None, root: Path = None) -> list:
    """
    Analyze Python files for imports from features.
    
    Args:
        staged_files: List of staged file paths (relative to repo root)
        state: Optional state dict (if not provided, will be loaded)
        root: Optional root path (defaults to REPO_ROOT)
    
    Returns:
        List of (file, module, req_id) tuples for imports from non-MERGED features
    """
    violations = []
    if state is None:
        state = load_state()
    if not state:
        return violations
    
    merged = get_merged_features(state)
    registry = state.get("feature_registry", {})
    repo_root = root if root is not None else REPO_ROOT
    
    for file_path in staged_files:
        if not file_path.endswith(".py"):
            continue
        
        full_path = repo_root / file_path
        if not full_path.exists():
            continue
        
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module.startswith("features.") or 
                        "features" in node.module.lower()
                    ):
                        req_id = get_feature_slug_from_path(node.module, registry)
                        if req_id and req_id not in merged:
                            violations.append((file_path, node.module, req_id))
                elif isinstance(node, ast.Import):
                    # Handle: import features.foo.bar
                    for alias in node.names:
                        full_name = alias.name
                        if "features" in full_name.lower():
                            req_id = get_feature_slug_from_path(full_name, registry)
                            if req_id and req_id not in merged:
                                violations.append((file_path, full_name, req_id))
        except Exception:
            # Skip files that can't be parsed (syntax errors, etc.)
            pass
    
    return violations


def analyze_javascript_imports(staged_files: list, state: dict = None, root: Path = None) -> list:
    """
    Analyze JavaScript/TypeScript files for imports from features.
    
    Uses regex pattern matching since we don't have a full JS parser.
    
    Args:
        staged_files: List of staged file paths (relative to repo root)
        state: Optional state dict (if not provided, will be loaded)
        root: Optional root path (defaults to REPO_ROOT)
    
    Returns:
        List of (file, module, req_id) tuples for imports from non-MERGED features
    """
    violations = []
    if state is None:
        state = load_state()
    if not state:
        return violations
    
    merged = get_merged_features(state)
    registry = state.get("feature_registry", {})
    repo_root = root if root is not None else REPO_ROOT
    
    # Regex patterns for JS/TS imports
    # Match: from 'features/foo' or import { foo } from 'features/foo'
    # Also: from "@/features/foo" (aliased features path)
    import_patterns = [
        re.compile(r'''from\s+['"]([^'"]+features[^'"]*)['"]''', re.MULTILINE),
        re.compile(r'''import\s+.*?\s+from\s+['"]([^'"]+features[^'"]*)['"]''', re.MULTILINE),
        re.compile(r'''require\s*\(\s*['"]([^'"]+features[^'"]*)['"]\s*\)''', re.MULTILINE),
    ]
    
    for file_path in staged_files:
        if not file_path.endswith((".ts", ".js", ".tsx", ".jsx")):
            continue
        
        full_path = repo_root / file_path
        if not full_path.exists():
            continue
        
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            for pattern in import_patterns:
                for match in pattern.finditer(content):
                    module = match.group(1)
                    req_id = get_feature_slug_from_path(module, registry)
                    if req_id and req_id not in merged:
                        violations.append((file_path, module, req_id))
        except Exception:
            # Skip files that can't be read
            pass
    
    return violations


def analyze_staged_imports(staged_files: list, state: dict = None, root: Path = None) -> list:
    """
    Analyze all staged files for imports from non-MERGED features.
    
    Args:
        staged_files: List of staged file paths (relative to repo root)
        state: Optional state dict (if not provided, will be loaded)
        root: Optional root path (defaults to REPO_ROOT)
    
    Returns:
        List of dicts with keys: file, module, req_id, feature_state
    """
    all_violations = []
    if state is None:
        state = load_state()
    if not state:
        return all_violations
    
    registry = state.get("feature_registry", {})
    repo_root = root if root is not None else REPO_ROOT
    
    # Combine Python and JS/TS analysis
    py_violations = analyze_python_imports(staged_files, state, repo_root)
    js_violations = analyze_javascript_imports(staged_files, state, repo_root)
    
    for file_path, module, req_id in py_violations + js_violations:
        entry = registry.get(req_id, {})
        feature_state = entry.get("state", "UNKNOWN")
        all_violations.append({
            "file": file_path,
            "module": module,
            "req_id": req_id,
            "feature_state": feature_state
        })
    
    return all_violations


def check_live_imports(staged_files: list) -> tuple:
    """
    Check staged files for live imports from non-MERGED features.
    
    This is the main entry point used by arbiter_check.py and pre-commit hook.
    
    Args:
        staged_files: List of staged file paths (relative to repo root)
    
    Returns:
        (has_violations, violations_list)
    """
    violations = analyze_staged_imports(staged_files)
    return bool(violations), violations


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


def get_staged_src_files() -> list:
    """Get list of staged src/ files."""
    stdout, rc = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if rc != 0 or not stdout:
        return []
    
    staged_files = [f.strip() for f in stdout.split("\n") if f.strip()]
    return [f for f in staged_files if f.startswith("src/")]


if __name__ == "__main__":
    import sys
    
    print("[IMPORT ANALYZER] Analyzing staged src/ files for live imports...")
    
    staged_files = get_staged_src_files()
    if not staged_files:
        print("[IMPORT ANALYZER] No staged src/ files found")
        sys.exit(0)
    
    print(f"[IMPORT ANALYZER] Found {len(staged_files)} staged src/ file(s)")
    
    has_violations, violations = check_live_imports(staged_files)
    
    if has_violations:
        print("[IMPORT ANALYZER] VIOLATIONS DETECTED:")
        for v in violations:
            print(f"  - {v['file']}: imports '{v['module']}' from {v['req_id']} (state={v['feature_state']})")
        print("[IMPORT ANALYZER] FOR-1(7)/TRC-2: Live imports from non-MERGED features are forbidden")
        print("[IMPORT ANALYZER] Use stub interfaces instead of live imports")
        sys.exit(1)
    else:
        print("[IMPORT ANALYZER] No live imports from non-MERGED features detected (ok)")
        sys.exit(0)
