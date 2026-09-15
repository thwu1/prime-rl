#!/usr/bin/env python3
"""Decrypt config from FWPK firmware, apply security hardening, re-encrypt."""
import json
import sys


def xor_crypt(data, key):
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def main():
    enc_path = sys.argv[1]        # encrypted config section
    meta_path = sys.argv[2]       # metadata JSON section (for key)
    out_enc_path = sys.argv[3]    # output re-encrypted config
    out_plain_path = sys.argv[4]  # output plaintext config

    with open(meta_path, "rb") as f:
        meta = json.loads(f.read())
    key = bytes.fromhex(meta["config_key"])

    with open(enc_path, "rb") as f:
        encrypted = f.read()

    plaintext = xor_crypt(encrypted, key).decode()
    print("Decrypted config:")
    print(plaintext)

    plaintext = plaintext.replace("tls_enabled=false", "tls_enabled=true")
    plaintext = plaintext.replace("cipher_suite=RC4-MD5", "cipher_suite=AES256-GCM")

    print("Modified config:")
    print(plaintext)

    with open(out_plain_path, "w") as f:
        f.write(plaintext)

    encrypted_new = xor_crypt(plaintext.encode(), key)
    with open(out_enc_path, "wb") as f:
        f.write(encrypted_new)


if __name__ == "__main__":
    main()
