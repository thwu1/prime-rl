#!/usr/bin/env python3
"""XAES-256-GCM file encryption tool.

Encrypts and decrypts files using XAES-256-GCM with a binary format:
  [8 bytes: magic "XAESFILE"]
  [1 byte: version 0x01]
  [24 bytes: nonce (random on encrypt)]
  [4 bytes: AAD length, uint32 big-endian]
  [N bytes: AAD]
  [remaining: XAES-256-GCM ciphertext || 16-byte tag]

"""

import argparse
import os
import struct
import sys

sys.path.insert(0, "/app/py_impl")
from xaes256gcm import XAES256GCM

MAGIC = b"XAESFILE"
VERSION = 0x01


def encrypt_file(key_hex, aad_text, input_path, output_path):
    """Encrypt a file using XAES-256-GCM with the binary format."""
    key = bytes.fromhex(key_hex)
    nonce = os.urandom(24)
    aad_bytes = aad_text.encode("utf-8") if aad_text else b""

    with open(input_path, "rb") as f:
        plaintext = f.read()

    cipher = XAES256GCM(key)
    ct = cipher.encrypt(nonce, plaintext, aad_bytes)

    with open(output_path, "wb") as f:
        f.write(MAGIC)
        f.write(bytes([VERSION]))
        f.write(nonce)
        f.write(struct.pack(">I", len(aad_bytes)))
        f.write(aad_bytes)
        f.write(ct)


def decrypt_file(key_hex, input_path, output_path):
    """Decrypt a file using XAES-256-GCM with the binary format."""
    key = bytes.fromhex(key_hex)

    with open(input_path, "rb") as f:
        data = f.read()

    if len(data) < 37:
        print("Error: file too short", file=sys.stderr)
        sys.exit(1)
    if data[:8] != MAGIC:
        print(f"Error: invalid file format (bad magic)", file=sys.stderr)
        sys.exit(1)
    if data[8] != VERSION:
        print(f"Error: unsupported version {data[8]}", file=sys.stderr)
        sys.exit(1)

    nonce = data[9:33]
    aad_len = struct.unpack(">I", data[33:37])[0]
    aad = data[37:37 + aad_len]
    ct = data[37 + aad_len:]

    cipher = XAES256GCM(key)
    plaintext = cipher.decrypt(nonce, ct, aad)

    with open(output_path, "wb") as f:
        f.write(plaintext)


def main():
    parser = argparse.ArgumentParser(description="XAES-256-GCM file encryption")
    sub = parser.add_subparsers(dest="command")

    enc = sub.add_parser("encrypt", help="Encrypt a file")
    enc.add_argument("--key", required=True, help="256-bit key as hex string")
    enc.add_argument("--aad", default="", help="Additional authenticated data (text)")
    enc.add_argument("input", help="Input file path")
    enc.add_argument("output", help="Output file path")

    dec = sub.add_parser("decrypt", help="Decrypt a file")
    dec.add_argument("--key", required=True, help="256-bit key as hex string")
    dec.add_argument("input", help="Encrypted input file path")
    dec.add_argument("output", help="Decrypted output file path")

    args = parser.parse_args()

    if args.command == "encrypt":
        encrypt_file(args.key, args.aad, args.input, args.output)
    elif args.command == "decrypt":
        decrypt_file(args.key, args.input, args.output)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
