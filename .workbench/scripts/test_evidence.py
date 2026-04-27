#!/usr/bin/env python3
"""
test_evidence.py — Test Execution Evidence Seal (TEES)

Owner: The Arbiter (Layer 2)
Version: 2.2
Location: .workbench/scripts/test_evidence.py

Implements FOR-1(4): Phase 2 Regression Enforcement via signed evidence tokens.

Mechanism:
- test_orchestrator.py outputs signed evidence tokens proving Phase 2 was run
- Pre-commit hook verifies evidence exists before allowing feature branch merge
- Post-commit hook stores evidence in `.workbench/test_evidence/seals/{commit}.seal`

Seal file format: JSON with commit, timestamp, phases, signature

Usage:
  python test_evidence.py create --commit <hash> --phase1 --phase2
  python test_evidence.py verify --commit <hash>
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Secret key for HMAC signing - in production this should be a proper secret
# For the workbench, we use a derived key from the repo root
REPO_ROOT = Path(__file__).parent.parent.parent
SECRETS_DIR = REPO_ROOT / ".workbench" / "secrets"
SEALS_DIR = REPO_ROOT / ".workbench" / "test_evidence" / "seals"

# Default HMAC secret (workbench identity key)
# In production, this should be loaded from a secure secrets manager
DEFAULT_SECRET = b"workbench-tees-secret-key-v1"

# FOR-1(1): CSTA — Transitions directory for state transition signatures
TRANSITIONS_DIR = REPO_ROOT / ".workbench" / "test_evidence" / "transitions"

# Arbiter key ID for CSTA signatures (identifies the signing authority)
ARBITER_KEY_ID = "arbiter-test-orchestrator-v1"


def _get_secret_key() -> bytes:
    """Get or create the HMAC secret key for seal signing."""
    secret_file = SECRETS_DIR / "tees-secret.key"
    
    if secret_file.exists():
        return secret_file.read_bytes()
    
    # Generate a new secret key
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    secret_key = os.urandom(32)
    secret_file.write_bytes(secret_key)
    return secret_key


def _sign(data: dict, secret: bytes = None) -> str:
    """Create HMAC-SHA256 signature for data dictionary."""
    if secret is None:
        secret = _get_secret_key()
    
    # Create deterministic JSON for signing
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature


def _verify(data: dict, signature: str, secret: bytes = None) -> bool:
    """Verify HMAC signature matches data."""
    if secret is None:
        secret = _get_secret_key()
    
    expected = _sign(data, secret)
    return hmac.compare_digest(expected, signature)


def create_seal(commit_hash: str, phase1_passed: bool, phase2_passed: bool) -> dict:
    """
    Create a signed evidence seal for test execution.
    
    Args:
        commit_hash: The git commit hash this seal is for
        phase1_passed: True if Phase 1 (feature scope) passed
        phase2_passed: True if Phase 2 (full regression) passed
    
    Returns:
        dict with commit, timestamp, phases, and signature
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    data = {
        "commit": commit_hash,
        "timestamp": timestamp,
        "phase1_passed": phase1_passed,
        "phase2_passed": phase2_passed,
    }
    
    signature = _sign(data)
    
    seal = {
        **data,
        "signature": signature,
    }
    
    return seal


def save_seal(commit_hash: str, seal: dict) -> Path:
    """
    Save a seal to the seals directory.
    
    Args:
        commit_hash: The commit hash this seal is for
        seal: The seal dictionary from create_seal()
    
    Returns:
        Path to the saved seal file
    """
    SEALS_DIR.mkdir(parents=True, exist_ok=True)
    
    seal_file = SEALS_DIR / f"{commit_hash}.seal"
    with open(seal_file, "w", encoding="utf-8") as f:
        json.dump(seal, f, indent=2)
        f.write("\n")
    
    return seal_file


def load_seal(commit_hash: str) -> dict:
    """
    Load a seal from the seals directory.
    
    Args:
        commit_hash: The commit hash to load seal for
    
    Returns:
        dict with seal data, or None if not found
    """
    seal_file = SEALS_DIR / f"{commit_hash}.seal"
    if not seal_file.exists():
        return None
    
    with open(seal_file, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_seal(commit_hash: str, require_phase2: bool = True) -> tuple:
    """
    Verify a seal exists and is valid.
    
    Args:
        commit_hash: The commit hash to verify
        require_phase2: If True, seal must have phase2_passed=True
    
    Returns:
        tuple of (is_valid: bool, message: str, details: dict)
    """
    seal = load_seal(commit_hash)
    
    if seal is None:
        return False, "No seal found for commit", {}
    
    # Extract signature and verify
    signature = seal.get("signature", "")
    data = {
        "commit": seal.get("commit"),
        "timestamp": seal.get("timestamp"),
        "phase1_passed": seal.get("phase1_passed"),
        "phase2_passed": seal.get("phase2_passed"),
    }
    
    # Verify signature
    if not _verify(data, signature):
        return False, "Invalid seal signature - seal may have been tampered", seal
    
    # Check Phase 2 requirement
    if require_phase2 and not seal.get("phase2_passed"):
        return False, "Phase 2 was not run or did not pass", seal
    
    return True, "Seal valid", seal


# =============================================================================
# FOR-1(1): CSTA — Cryptographic State Transition Attribution
# =============================================================================

def create_state_transition_signature(state_from: str, state_to: str, req_id: str, timestamp: str = None) -> dict:
    """
    Create a signed state transition attestation.
    
    This function is called ONLY by the Arbiter (test_orchestrator.py) when
    transitioning state. Agents cannot self-sign state transitions.
    
    Args:
        state_from: The previous state (e.g., "RED", "FEATURE_GREEN")
        state_to: The new state (e.g., "GREEN", "MERGED")
        req_id: The REQ-ID being transitioned (e.g., "REQ-001")
        timestamp: ISO timestamp, defaults to current UTC time
    
    Returns:
        dict with from_state, to_state, req_id, timestamp, arbiter_key_id, signature
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    
    data = {
        "from_state": state_from,
        "to_state": state_to,
        "req_id": req_id,
        "timestamp": timestamp,
        "arbiter_key_id": ARBITER_KEY_ID,
    }
    
    signature = _sign(data)
    
    return {
        **data,
        "signature": signature,
    }


def save_state_transition_signature(state_from: str, state_to: str, req_id: str, sig: dict = None) -> Path:
    """
    Save a state transition signature to the transitions directory.
    
    File format: .workbench/test_evidence/transitions/{req_id}_{from}_{to}.sig
    
    Args:
        state_from: The previous state
        state_to: The new state
        req_id: The REQ-ID
        sig: Optional pre-created signature dict; if None, creates new one
    
    Returns:
        Path to the saved signature file
    """
    TRANSITIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    sig_file = TRANSITIONS_DIR / f"{req_id}_{state_from}_{state_to}.sig"
    
    if sig is None:
        sig = create_state_transition_signature(state_from, state_to, req_id)
    
    with open(sig_file, "w", encoding="utf-8") as f:
        json.dump(sig, f, indent=2)
        f.write("\n")
    
    return sig_file


def load_state_transition_signature(state_from: str, state_to: str, req_id: str) -> dict:
    """
    Load a state transition signature from the transitions directory.
    
    Args:
        state_from: The previous state
        state_to: The new state
        req_id: The REQ-ID
    
    Returns:
        dict with signature data, or None if not found
    """
    sig_file = TRANSITIONS_DIR / f"{req_id}_{state_from}_{state_to}.sig"
    if not sig_file.exists():
        return None
    
    with open(sig_file, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_state_transition_signature(state_from: str, state_to: str, req_id: str) -> tuple:
    """
    Verify a state transition signature is valid.
    
    This verifies:
    1. The signature file exists
    2. The signature was created by the Arbiter (correct key_id)
    3. The signature matches the transition data (not tampered)
    
    Args:
        state_from: Expected previous state
        state_to: Expected new state
        req_id: The REQ-ID
    
    Returns:
        tuple of (is_valid: bool, message: str, details: dict)
    """
    sig = load_state_transition_signature(state_from, state_to, req_id)
    
    if sig is None:
        return False, f"No signature found for {req_id} transition {state_from}→{state_to}", {}
    
    # Verify arbiter key ID
    if sig.get("arbiter_key_id") != ARBITER_KEY_ID:
        return False, "Invalid arbiter key ID — signature not from Arbiter", sig
    
    # Extract and verify signature
    signature = sig.get("signature", "")
    data = {
        "from_state": sig.get("from_state"),
        "to_state": sig.get("to_state"),
        "req_id": sig.get("req_id"),
        "timestamp": sig.get("timestamp"),
        "arbiter_key_id": sig.get("arbiter_key_id"),
    }
    
    if not _verify(data, signature):
        return False, "Invalid signature — transition data may have been tampered", sig
    
    # Verify state values match
    if data["from_state"] != state_from or data["to_state"] != state_to:
        return False, "State values mismatch in signature", sig
    
    return True, "Signature valid", sig


def main():
    parser = argparse.ArgumentParser(description="Test Evidence Seal (TEES) Tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # create command
    create_parser = subparsers.add_parser("create", help="Create a new evidence seal")
    create_parser.add_argument("--commit", required=True, help="Git commit hash")
    create_parser.add_argument("--phase1", action="store_true", help="Phase 1 passed")
    create_parser.add_argument("--phase2", action="store_true", help="Phase 2 passed")
    
    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verify an evidence seal")
    verify_parser.add_argument("--commit", required=True, help="Git commit hash")
    verify_parser.add_argument("--no-require-phase2", action="store_true", help="Do not require Phase 2")
    
    args = parser.parse_args()
    
    if args.command == "create":
        seal = create_seal(args.commit, args.phase1, args.phase2)
        seal_file = save_seal(args.commit, seal)
        print(f"[TEST EVIDENCE] Seal created: {seal_file}")
        print(f"  Commit: {seal['commit']}")
        print(f"  Phase1: {seal['phase1_passed']}")
        print(f"  Phase2: {seal['phase2_passed']}")
        print(f"  Timestamp: {seal['timestamp']}")
        print(f"  Signature: {seal['signature'][:16]}...")
        sys.exit(0)
    
    elif args.command == "verify":
        is_valid, message, details = verify_seal(
            args.commit, 
            require_phase2=not args.no_require_phase2
        )
        
        if is_valid:
            print(f"[TEST EVIDENCE] OK: {message}")
            print(f"  Commit: {details.get('commit')}")
            print(f"  Phase1: {details.get('phase1_passed')}")
            print(f"  Phase2: {details.get('phase2_passed')}")
            sys.exit(0)
        else:
            print(f"[TEST EVIDENCE] FAILED: {message}")
            print(f"  Commit: {args.commit}")
            sys.exit(1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
