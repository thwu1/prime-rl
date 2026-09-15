#!/usr/bin/env python3
"""Verification harness for VaultSync security audit."""
import sys
sys.path.insert(0, '/app')

from vaultsync import Server, AttackParams
from dissononce.dh.x25519.x25519 import X25519DH

import solution


def main():
    server = Server()
    client_keypair = X25519DH().generate_keypair()
    server.register_user(client_keypair.public)
    params = AttackParams(client_keypair, server)

    print("Test 1: Signing key recovery")
    recovered_key = solution.recover_signing_key(params)
    if recovered_key == server.ecdsa_sk:
        print("  PASS")
    else:
        print("  FAIL: recovered key does not match")
        sys.exit(1)

    print("Test 2: Vault update forgery")
    target_data = b"VaultSync security audit: storage compromised"
    solution.forge_vault_update(params, target_data)
    if server.get_user_storage() == target_data:
        print("  PASS")
    else:
        print("  FAIL: storage was not modified to target data")
        sys.exit(1)

    print("\nAll tests passed!")


if __name__ == "__main__":
    main()
