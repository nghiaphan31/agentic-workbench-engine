#!/usr/bin/env python3
"""
mode_keys.py — Cryptographic Mode Signing (CMS) for Agent Modes

Owner: The Arbiter (Layer 2)
Version: 2.2
Location: .workbench/scripts/mode_keys.py

Provides Ed25519 key pair management and signing for agent modes.
Each mode has a unique key pair for signing pivot branch assertions.

Modes:
- architect: May initiate Stage 1 pivots
- developer: May request pivots but needs Architect approval
- test_engineer: Test engineer mode
- orchestrator: Orchestrator mode
- documentation-librarian: Documentation/librarian mode

Usage:
  python mode_keys.py generate          # Generate all mode key pairs
  python mode_keys.py sign <mode> <ticket_id> <branch>  # Sign a pivot assertion
  python mode_keys.py verify <mode> <ticket_id> <branch> <signature>  # Verify signature
"""

import argparse
import hashlib
import json
import os
import sys
import base64
from pathlib import Path
from typing import Optional, Tuple

# Try to import cryptography library, fallback to hashlib if not available
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

REPO_ROOT = Path(__file__).parent.parent.parent
KEYS_DIR = REPO_ROOT / ".workbench" / "keys" / "mode_keys"

# All supported modes
MODES = ["architect", "developer", "test_engineer", "orchestrator", "documentation-librarian"]


class ModeSigner:
    """
    Cryptographic Mode Signing for Agent Modes.
    
    Provides Ed25519 key pair generation, signing, and verification
    for pivot branch assertions. Only the Architect mode may sign
    pivot branch creation (per PVT-2).
    """
    
    def __init__(self, keys_dir: Path = None):
        self.keys_dir = keys_dir or KEYS_DIR
        self.keys_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_private_key_path(self, mode: str) -> Path:
        """Get path to mode's private key."""
        return self.keys_dir / f"{mode}_private.pem"
    
    def _get_public_key_path(self, mode: str) -> Path:
        """Get path to mode's public key."""
        return self.keys_dir / f"{mode}_public.pem"
    
    def _generate_message_hash(self, pivot_ticket_id: str, branch_name: str) -> bytes:
        """
        Generate deterministic message hash for signing.
        
        This creates a canonical representation of the pivot assertion
        that can be verified later without ambiguity.
        """
        # Normalize branch name
        canonical_branch = branch_name.strip().lstrip("refs/heads/")
        
        message = f"pivot:{pivot_ticket_id}:branch:{canonical_branch}"
        return hashlib.sha256(message.encode("utf-8")).digest()
    
    def generate_keys(self, mode: str) -> Tuple[str, str]:
        """
        Generate Ed25519 key pair for a mode.
        
        Returns:
            Tuple of (private_key_pem, public_key_pem)
        """
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}. Must be one of {MODES}")
        
        private_key_path = self._get_private_key_path(mode)
        public_key_path = self._get_public_key_path(mode)
        
        if HAS_CRYPTOGRAPHY:
            # Use Ed25519 from cryptography library
            private_key = Ed25519PrivateKey.generate()
            
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            public_pem = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        else:
            raise RuntimeError(
                "cryptography library not available. "
                "Install with: pip install cryptography"
            )
        
        # Store keys
        private_key_path.write_bytes(private_pem)
        public_key_path.write_bytes(public_pem)
        
        # Set restrictive permissions (owner only)
        os.chmod(private_key_path, 0o600)
        os.chmod(public_key_path, 0o644)
        
        return private_pem.decode("utf-8"), public_pem.decode("utf-8")
    
    def _load_private_key(self, mode: str) -> Ed25519PrivateKey:
        """Load private key for a mode."""
        private_key_path = self._get_private_key_path(mode)
        if not private_key_path.exists():
            raise FileNotFoundError(
                f"Private key not found for mode '{mode}'. "
                f"Run: python mode_keys.py generate"
            )
        
        if HAS_CRYPTOGRAPHY:
            private_bytes = private_key_path.read_bytes()
            return serialization.load_pem_private_key(
                private_bytes,
                password=None,
                backend=default_backend()
            )
        else:
            raise RuntimeError("cryptography library not available")
    
    def _load_public_key(self, mode: str) -> Ed25519PublicKey:
        """Load public key for a mode."""
        public_key_path = self._get_public_key_path(mode)
        if not public_key_path.exists():
            raise FileNotFoundError(
                f"Public key not found for mode '{mode}'. "
                f"Run: python mode_keys.py generate"
            )
        
        if HAS_CRYPTOGRAPHY:
            public_bytes = public_key_path.read_bytes()
            return serialization.load_pem_public_key(
                public_bytes,
                backend=default_backend()
            )
        else:
            raise RuntimeError("cryptography library not available")
    
    def architect_sign(self, pivot_ticket_id: str, branch_name: str) -> str:
        """
        Sign a pivot assertion with the Architect's private key.
        
        This creates a cryptographic assertion that the Architect Agent
        has authorized a pivot branch creation.
        
        Args:
            pivot_ticket_id: The ticket ID being pivoted (e.g., "REQ-042")
            branch_name: The pivot branch name (e.g., "pivot/REQ-042-fix")
        
        Returns:
            Base64-encoded Ed25519 signature
        """
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("cryptography library not available")
        
        # Load architect's private key
        private_key = self._load_private_key("architect")
        
        # Create message hash
        message_hash = self._generate_message_hash(pivot_ticket_id, branch_name)
        
        # Sign
        signature = private_key.sign(message_hash)
        
        # Return base64-encoded signature
        return base64.b64encode(signature).decode("utf-8")
    
    def verify_signature(
        self,
        pivot_ticket_id: str,
        branch_name: str,
        signature: str,
        signing_mode: str = "architect"
    ) -> bool:
        """
        Verify a pivot assertion signature.
        
        Args:
            pivot_ticket_id: The ticket ID being pivoted
            branch_name: The pivot branch name
            signature: Base64-encoded Ed25519 signature
            signing_mode: The mode that signed (default: architect)
        
        Returns:
            True if signature is valid, False otherwise
        """
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("cryptography library not available")
        
        try:
            # Decode signature
            signature_bytes = base64.b64decode(signature)
            
            # Load public key for the signing mode
            public_key = self._load_public_key(signing_mode)
            
            # Create message hash
            message_hash = self._generate_message_hash(pivot_ticket_id, branch_name)
            
            # Verify signature
            public_key.verify(signature_bytes, message_hash)
            return True
        except Exception:
            return False
    
    def keys_exist(self, mode: str) -> bool:
        """Check if key pair exists for a mode."""
        private_path = self._get_private_key_path(mode)
        public_path = self._get_public_key_path(mode)
        return private_path.exists() and public_path.exists()
    
    def all_keys_exist(self) -> bool:
        """Check if all mode key pairs exist."""
        return all(self.keys_exist(mode) for mode in MODES)
    
    def generate_all_keys(self) -> dict:
        """
        Generate key pairs for all modes.
        
        Returns:
            Dict mapping mode names to (private_pem, public_pem) tuples
        """
        results = {}
        for mode in MODES:
            if not self.keys_exist(mode):
                private_pem, public_pem = self.generate_keys(mode)
                results[mode] = (private_pem, public_pem)
            else:
                results[mode] = ("<already exists>", "<already exists>")
        return results
    
    def get_architect_public_key_pem(self) -> str:
        """Get the Architect's public key in PEM format."""
        public_key_path = self._get_public_key_path("architect")
        if not public_key_path.exists():
            raise FileNotFoundError(
                "Architect public key not found. "
                "Run: python mode_keys.py generate"
            )
        return public_key_path.read_text(encoding="utf-8")


def generate_all(args):
    """Generate key pairs for all modes."""
    signer = ModeSigner()
    
    if signer.all_keys_exist() and not args.force:
        print("[MODE_KEYS] All mode keys already exist. Use --force to regenerate.")
        print("Keys directory:", signer.keys_dir)
        for mode in MODES:
            priv_path = signer._get_private_key_path(mode)
            pub_path = signer._get_public_key_path(mode)
            print(f"  {mode}: private={priv_path}, public={pub_path}")
        return
    
    print("[MODE_KEYS] Generating Ed25519 key pairs for all modes...")
    results = signer.generate_all_keys()
    
    for mode, (private_pem, public_pem) in results.items():
        status = "generated" if private_pem != "<already exists>" else "exists"
        print(f"  {mode}: {status}")
    
    print("[MODE_KEYS] Key generation complete.")
    print("Keys stored in:", signer.keys_dir)


def sign_command(args):
    """Sign a pivot assertion."""
    signer = ModeSigner()
    
    if args.mode != "architect":
        print(f"[MODE_KEYS] ERROR: Only Architect mode may sign pivot assertions.")
        print(f"  Requested mode: {args.mode}")
        print(f"  Only architect can sign (per PVT-2)")
        sys.exit(1)
    
    try:
        signature = signer.architect_sign(args.ticket_id, args.branch)
        
        # Output signature in a format suitable for git notes
        print(f"[MODE_KEYS] Pivot assertion signed successfully.")
        print(f"  Ticket: {args.ticket_id}")
        print(f"  Branch: {args.branch}")
        print(f"  Signature: {signature}")
        print()
        print("To store in git notes:")
        print(f"  git notes --ref=pivot-signature add -m 'architect:{signature}' HEAD")
        
        return signature
    except Exception as e:
        print(f"[MODE_KEYS] ERROR: {e}")
        sys.exit(1)


def verify_command(args):
    """Verify a pivot assertion signature."""
    signer = ModeSigner()
    
    try:
        is_valid = signer.verify_signature(
            args.ticket_id,
            args.branch,
            args.signature,
            signing_mode=args.mode
        )
        
        if is_valid:
            print(f"[MODE_KEYS] Signature VERIFIED.")
            print(f"  Mode: {args.mode}")
            print(f"  Ticket: {args.ticket_id}")
            print(f"  Branch: {args.branch}")
        else:
            print(f"[MODE_KEYS] Signature INVALID or TAMPERED.")
            print(f"  Mode: {args.mode}")
            print(f"  Ticket: {args.ticket_id}")
            print(f"  Branch: {args.branch}")
            print(f"  Signature: {args.signature[:32]}...")
            sys.exit(1)
        
        return is_valid
    except Exception as e:
        print(f"[MODE_KEYS] ERROR: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Cryptographic Mode Signing (CMS) for Agent Modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mode_keys.py generate           # Generate all mode keys
  python mode_keys.py sign architect REQ-042 pivot/REQ-042-fix
  python mode_keys.py verify architect REQ-042 pivot/REQ-042-fix <signature>
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate all mode key pairs")
    gen_parser.add_argument("--force", action="store_true", help="Regenerate existing keys")
    
    # sign command
    sign_parser = subparsers.add_parser("sign", help="Sign a pivot assertion (Architect only)")
    sign_parser.add_argument("mode", help="Mode signing the assertion")
    sign_parser.add_argument("ticket_id", help="Pivot ticket ID (e.g., REQ-042)")
    sign_parser.add_argument("branch", help="Pivot branch name")
    
    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verify a pivot assertion signature")
    verify_parser.add_argument("mode", help="Mode that signed (default: architect)")
    verify_parser.add_argument("ticket_id", help="Pivot ticket ID")
    verify_parser.add_argument("branch", help="Pivot branch name")
    verify_parser.add_argument("signature", help="Base64-encoded Ed25519 signature")
    
    args = parser.parse_args()
    
    if args.command == "generate":
        generate_all(args)
    elif args.command == "sign":
        sign_command(args)
    elif args.command == "verify":
        verify_command(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
