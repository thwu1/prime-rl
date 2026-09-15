
"""
OpenBao Transit BYOK Import and Cryptographic Pipeline.
"""

import json
import base64
import os
import sys
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.keywrap import aes_key_wrap_with_padding

BAO_ADDR = "http://127.0.0.1:8200"
TOKEN = sys.argv[1]
HEADERS = {"X-Vault-Token": TOKEN}


def api(method, path, data=None):
    url = f"{BAO_ADDR}/v1/{path}"
    if method == "GET":
        r = requests.get(url, headers=HEADERS)
    elif method == "POST":
        r = requests.post(url, headers=HEADERS, json=data)
    elif method == "LIST":
        r = requests.request("LIST", url, headers=HEADERS)
    else:
        raise ValueError(f"Unsupported method: {method}")
    r.raise_for_status()
    if r.text:
        return r.json()
    return {}


def byok_wrap(wrapping_key_pem, target_key_pem):
    wrapping_key = serialization.load_pem_public_key(wrapping_key_pem.encode())

    target_key = serialization.load_pem_private_key(
        target_key_pem.encode(), password=None
    )

    target_key_bytes = target_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    ephemeral_aes_key = os.urandom(32)

    wrapped_target = aes_key_wrap_with_padding(ephemeral_aes_key, target_key_bytes)

    wrapped_aes = wrapping_key.encrypt(
        ephemeral_aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    ciphertext = wrapped_aes + wrapped_target

    return base64.b64encode(ciphertext).decode()


def main():
    # Create native Transit keys
    api("POST", "transit/keys/data-enc", {
        "type": "aes256-gcm96",
        "convergent_encryption": True,
        "derived": True,
    })
    api("POST", "transit/keys/hmac-auth", {
        "type": "hmac",
        "key_size": 64,
    })

    # Retrieve Transit wrapping key for BYOK
    wrapping_key_data = api("GET", "transit/wrapping_key")
    wrapping_key_pem = wrapping_key_data["data"]["public_key"]

    # Import RSA-4096 via BYOK
    with open("/app/keys/rsa4096.pem") as f:
        rsa_pem = f.read()
    rsa_ciphertext = byok_wrap(wrapping_key_pem, rsa_pem)
    api("POST", "transit/keys/imported-rsa/import", {
        "type": "rsa-4096",
        "ciphertext": rsa_ciphertext,
        "exportable": True,
        "allow_plaintext_backup": True,
    })

    # Import ed25519 via BYOK
    with open("/app/keys/ed25519.pem") as f:
        ed25519_pem = f.read()
    ed25519_ciphertext = byok_wrap(wrapping_key_pem, ed25519_pem)
    api("POST", "transit/keys/imported-ed25519/import", {
        "type": "ed25519",
        "ciphertext": ed25519_ciphertext,
    })

    # Encrypt records with convergent encryption
    with open("/app/data/records.json") as f:
        records = json.load(f)["records"]

    encrypted_records = []
    for record in records:
        plaintext_b64 = base64.b64encode(record["data"].encode()).decode()
        context = base64.b64encode(record["id"].encode()).decode()
        result = api("POST", "transit/encrypt/data-enc", {
            "plaintext": plaintext_b64,
            "context": context,
        })
        encrypted_records.append({
            "id": record["id"],
            "ciphertext": result["data"]["ciphertext"],
        })

    # Rotate data-enc 3 times (to version 4)
    for i in range(3):
        api("POST", "transit/keys/data-enc/rotate", {})

    # Rewrap all ciphertexts to latest version
    for i, record in enumerate(encrypted_records):
        context = base64.b64encode(record["id"].encode()).decode()
        result = api("POST", "transit/rewrap/data-enc", {
            "ciphertext": record["ciphertext"],
            "context": context,
        })
        encrypted_records[i]["ciphertext"] = result["data"]["ciphertext"]

    with open("/app/output/encrypted_records.json", "w") as f:
        json.dump({"records": encrypted_records}, f, indent=2)

    # Set min version constraints
    api("POST", "transit/keys/data-enc/config", {
        "min_decryption_version": 3,
        "min_encryption_version": 4,
    })

    # Sign each rewrapped ciphertext with ed25519
    signatures = []
    for record in encrypted_records:
        input_b64 = base64.b64encode(record["ciphertext"].encode()).decode()
        result = api("POST", "transit/sign/imported-ed25519", {
            "input": input_b64,
        })
        signatures.append({
            "id": record["id"],
            "signature": result["data"]["signature"],
        })

    with open("/app/output/signatures.json", "w") as f:
        json.dump({"signatures": signatures}, f, indent=2)

    # Generate SHA-512 HMACs for original plaintext
    hmacs = []
    for record in records:
        input_b64 = base64.b64encode(record["data"].encode()).decode()
        result = api("POST", "transit/hmac/hmac-auth/sha2-512", {
            "input": input_b64,
        })
        hmacs.append({
            "id": record["id"],
            "hmac": result["data"]["hmac"],
        })

    with open("/app/output/hmacs.json", "w") as f:
        json.dump({"hmacs": hmacs}, f, indent=2)

    # Export RSA public key
    rsa_export = api("GET", "transit/export/public-key/imported-rsa/latest")
    keys = rsa_export["data"]["keys"]
    latest_version = max(keys.keys(), key=int)
    rsa_pub = keys[latest_version]
    with open("/app/output/rsa_public_key.pem", "w") as f:
        f.write(rsa_pub)

    # Generate key status report
    key_names = ["data-enc", "hmac-auth", "imported-rsa", "imported-ed25519"]
    key_status = []
    for name in key_names:
        data = api("GET", f"transit/keys/{name}")["data"]
        key_status.append({
            "name": data["name"],
            "type": data["type"],
            "latest_version": data["latest_version"],
            "min_decryption_version": data["min_decryption_version"],
            "min_encryption_version": data["min_encryption_version"],
            "supports_encryption": data["supports_encryption"],
            "supports_signing": data["supports_signing"],
            "exportable": data.get("exportable", False),
            "allow_plaintext_backup": data.get("allow_plaintext_backup", False),
        })

    with open("/app/output/key_status.json", "w") as f:
        json.dump({"keys": key_status}, f, indent=2)


if __name__ == "__main__":
    main()
