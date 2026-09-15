#!/usr/bin/env python3
"""
Generate a captured QUIC v1 Initial packet for the analysis task.
Run at Docker build time; removed afterward.

"""
import json
import os
import hmac
import hashlib
import struct

from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def hkdf_expand_label(secret, label, length):
    full_label = b"tls13 " + label
    info = struct.pack(">H", length) + bytes([len(full_label)]) + full_label + b"\x00"
    return HKDFExpand(
        algorithm=hashes.SHA256(), length=length, info=info
    ).derive(secret)


def main():
    os.makedirs("/app/capture", exist_ok=True)

    # Connection parameters
    dcid = bytes.fromhex("a1b2c3d4e5f60718")
    scid = bytes.fromhex("0011")
    version = 0x00000001
    pn = 0
    pn_length = 1

    # Plaintext: CRYPTO frame with forensics data + PADDING
    crypto_data = b"QUIC-Forensics-Bench-Capture-Data"
    crypto_frame = bytes([0x06, 0x00, len(crypto_data)]) + crypto_data
    plaintext = crypto_frame + bytes(80)

    # Derive v1 client keys
    salt = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
    initial_secret = hmac.new(salt, dcid, hashlib.sha256).digest()
    cs = hkdf_expand_label(initial_secret, b"client in", 32)
    key = hkdf_expand_label(cs, b"quic key", 16)
    iv = hkdf_expand_label(cs, b"quic iv", 12)
    hp = hkdf_expand_label(cs, b"quic hp", 16)

    # Build unprotected header
    first_byte = 0xC0 | (pn_length - 1)
    pn_bytes = pn.to_bytes(pn_length, "big")
    header = bytes([first_byte])
    header += version.to_bytes(4, "big")
    header += bytes([len(dcid)]) + dcid
    header += bytes([len(scid)]) + scid
    header += bytes([0])  # Token length = 0
    total_len = pn_length + len(plaintext) + 16
    header += (0x4000 | total_len).to_bytes(2, "big")
    header += pn_bytes

    # AEAD encrypt
    nonce = bytearray(iv)
    pn_pad = pn.to_bytes(len(nonce), "big")
    for i in range(len(nonce)):
        nonce[i] ^= pn_pad[i]
    ct = AESGCM(key).encrypt(bytes(nonce), plaintext, header)

    # Apply header protection
    pn_offset = len(header) - pn_length
    full = header + ct
    sample = full[pn_offset + 4 : pn_offset + 4 + 16]
    mask = Cipher(algorithms.AES(hp), modes.ECB()).encryptor().update(sample)
    pf = first_byte ^ (mask[0] & 0x0F)
    ppn = bytearray(pn_bytes)
    for i in range(pn_length):
        ppn[i] ^= mask[1 + i]
    protected = bytes([pf]) + full[1:pn_offset] + bytes(ppn) + ct

    # Write outputs
    with open("/app/capture/packet.hex", "w") as f:
        f.write(protected.hex())

    with open("/app/capture/metadata.json", "w") as f:
        json.dump({
            "dcid": dcid.hex(),
            "description": "QUIC v1 client Initial packet from test deployment"
        }, f, indent=2)


if __name__ == "__main__":
    main()
