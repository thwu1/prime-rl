#!/usr/bin/env python3
"""

Decrypt files encrypted with the InlaneFreight Secure Vault Tool v2.3.
Reads the tool's config to obtain KDF and cipher parameters.
"""
import hashlib
import struct
import sys
from configparser import ConfigParser

from Crypto.Cipher import AES


def decrypt_vault_file(input_path, output_path, password, config_path):
    # Load parameters from config
    c = ConfigParser()
    c.read(config_path)

    iterations = c.getint("kdf", "pbkdf2_iterations")
    hash_algo = c.get("kdf", "hash_algorithm")
    key_len = c.getint("cipher", "key_length")
    nonce_len = c.getint("cipher", "nonce_length")

    with open(input_path, "rb") as f:
        data = f.read()

    # Parse the IFVT file format
    magic = data[:4]
    assert magic == b"IFVT", f"Invalid magic: {magic}"

    ver = struct.unpack(">H", data[4:6])[0]
    assert ver == 0x0203, f"Unsupported version: {ver:#06x}"

    salt_len = struct.unpack(">H", data[6:8])[0]
    salt = data[8 : 8 + salt_len]
    nonce = data[8 + salt_len : 8 + salt_len + nonce_len]
    tag = data[-16:]
    ciphertext = data[8 + salt_len + nonce_len : -16]

    # Derive key using PBKDF2-HMAC-SHA256
    key = hashlib.pbkdf2_hmac(
        hash_algo, password.encode("utf-8"), salt, iterations, dklen=key_len
    )

    # Decrypt using AES-256-GCM
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)

    with open(output_path, "wb") as f:
        f.write(plaintext)

    return plaintext.decode("utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            f"Usage: {sys.argv[0]} <input> <output> <password> <config>",
            file=sys.stderr,
        )
        sys.exit(1)
    result = decrypt_vault_file(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    print(f"[+] Decrypted successfully:\n{result}")
