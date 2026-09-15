"""Batch encryption of plaintext records."""
import json
import os
import hashlib
from keymanager import load_master_key, derive_record_key
from crypto import encrypt


def generate_nonce(seed, index):
    """Deterministic 24-byte nonce from seed and record index."""
    return hashlib.shake_128(seed + index.to_bytes(4, "big")).digest(24)


def main():
    master_key = load_master_key()
    nonce_seed = hashlib.sha256(master_key + b"nonce-generation").digest()

    plaintext_dir = "/app/data/plaintext"
    output_dir = "/app/data/encrypted"
    os.makedirs(output_dir, exist_ok=True)

    for fname in sorted(os.listdir(plaintext_dir)):
        if not fname.endswith(".json"):
            continue
        record_id = fname.replace(".json", "")
        idx = int(record_id.split("_")[1])

        with open(os.path.join(plaintext_dir, fname)) as f:
            plaintext_bytes = f.read().encode()

        key = derive_record_key(master_key, record_id)
        nonce = generate_nonce(nonce_seed, idx)
        aad = f"audit-svc:{record_id}"

        ciphertext = encrypt(key, nonce, plaintext_bytes, aad.encode())

        enc_data = {
            "record_id": record_id,
            "nonce_hex": nonce.hex(),
            "aad": aad,
            "ciphertext_hex": ciphertext.hex(),
        }
        with open(os.path.join(output_dir, f"{record_id}.enc"), "w") as f:
            json.dump(enc_data, f, indent=2)

        print(f"Encrypted {record_id}")


if __name__ == "__main__":
    main()
