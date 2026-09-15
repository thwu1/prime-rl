#!/usr/bin/env python3
"""
VaultSync challenge setup script.

Generates the server state from a random DH master key, collects public
artifacts (DH public key, ECDSA signatures, Noise public keys), and saves
them to /app/public_data.json.

This script is deleted after execution during the Docker build.
"""

import os
import sys
import json
import base64

sys.path.insert(0, "/app")
from vaultsync import (
    VaultSyncServer, DH_MOD, DH_GEN, ECDSA,
    make_client_message,
)
from dissononce.dh.x25519.x25519 import X25519DH


def main():
    # Generate a random DH private key — this is the master secret.
    # It exists only during this build step and is never persisted.
    raw = os.urandom(16)
    dh_sk = int.from_bytes(raw, "big") % (DH_MOD - 1)
    if dh_sk == 0:
        dh_sk = 1

    # Create server
    server = VaultSyncServer(dh_sk)

    # Generate a registered user's Noise keypair and register them
    client_keypair = X25519DH().generate_keypair()
    server.register_user(client_keypair.public)

    # Collect 20 signed update-check responses
    signed_updates = []
    for i in range(20):
        msg, (r, s) = server.check_update()
        signed_updates.append({
            "message": base64.b64encode(msg).decode(),
            "signature_r": str(r),
            "signature_s": str(s),
        })

    # Perform one legitimate storage update (so there is existing data)
    legit_msg = make_client_message(
        client_keypair, server.get_noise_public_key(), b"user_backup_v3.dat"
    )
    server.update_storage(legit_msg)

    # ECDSA public key coordinates
    ecdsa_pk = server.get_ecdsa_public_key()

    # Save all public data
    public_data = {
        "dh_params": {
            "mod": str(DH_MOD),
            "gen": str(DH_GEN),
            "order_factorization": [[2, 3], [67, 3], [131, 5], [257, 3], [521, 1], [1031, 4]],
        },
        "dh_public_key": str(server.get_dh_public_key()),
        "ecdsa_public_key": {
            "x": str(ecdsa_pk.x),
            "y": str(ecdsa_pk.y),
            "curve": "secp256r1",
        },
        "noise_static_public_key": base64.b64encode(
            server.get_noise_public_key().data
        ).decode(),
        "client_noise_public_key": base64.b64encode(
            client_keypair.public.data
        ).decode(),
        "signed_updates": signed_updates,
        "target_payload": base64.b64encode(
            b"SECURITY AUDIT: STORAGE COMPROMISED"
        ).decode(),
        "current_storage": base64.b64encode(server.get_storage()).decode(),
    }

    with open("/app/public_data.json", "w") as f:
        json.dump(public_data, f, indent=2)

    print("Setup complete. Public data written to /app/public_data.json")


if __name__ == "__main__":
    main()
