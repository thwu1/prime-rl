#!/usr/bin/env python3
"""
BYOK (Bring Your Own Key) import helper for OpenBao Transit secrets engine.

Implements the secure key import protocol required by Transit:
fetches the wrapping key, performs the cryptographic wrapping operations,
and submits the wrapped key material to the import endpoint.
"""

import sys
import os
import base64
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.keywrap import aes_key_wrap_with_padding


def import_key_byok(bao_addr, bao_token, key_name, target_key_bytes,
                    key_type="aes256-gcm96", exportable=True):
    headers = {"X-Vault-Token": bao_token}

    # Fetch the Transit wrapping key (4096-bit RSA public key)
    r = requests.get(f"{bao_addr}/v1/transit/wrapping_key", headers=headers)
    r.raise_for_status()
    wrapping_key_pem = r.json()["data"]["public_key"]
    wrapping_key = load_pem_public_key(wrapping_key_pem.encode())

    # Generate ephemeral AES-256 key
    ephemeral_key = os.urandom(32)

    # Wrap target key with ephemeral AES key using AES-KWP (RFC 5649)
    wrapped_target = aes_key_wrap_with_padding(ephemeral_key, target_key_bytes)

    # Wrap ephemeral key with RSA-OAEP (SHA-256 hash, MGF1-SHA-256)
    wrapped_ephemeral = wrapping_key.encrypt(
        ephemeral_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    # Construct ciphertext = wrapped_ephemeral (512 bytes) || wrapped_target
    ciphertext = base64.b64encode(wrapped_ephemeral + wrapped_target).decode()

    # Submit to Transit import endpoint
    payload = {
        "type": key_type,
        "ciphertext": ciphertext,
        "hash_function": "SHA256",
        "exportable": exportable,
        "allow_plaintext_backup": True
    }

    r = requests.post(
        f"{bao_addr}/v1/transit/keys/{key_name}/import",
        headers=headers,
        json=payload
    )
    r.raise_for_status()
    print(f"Successfully imported key '{key_name}' via BYOK")


if __name__ == "__main__":
    bao_addr = os.environ.get("BAO_ADDR",
                              os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"))
    bao_token = os.environ.get("BAO_TOKEN",
                               os.environ.get("VAULT_TOKEN", "test-root-token"))

    key_name = sys.argv[1]
    key_hex_file = sys.argv[2]

    with open(key_hex_file) as f:
        key_hex = f.read().strip()

    target_key = bytes.fromhex(key_hex)
    import_key_byok(bao_addr, bao_token, key_name, target_key)
