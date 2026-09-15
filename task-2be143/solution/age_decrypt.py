#!/usr/bin/env python3
"""
age v1 X25519 decryptor — reference solution.

Implements the age-encryption.org/v1 decryption pipeline for X25519
recipients using only the Python `cryptography` library for low-level
primitives.  No external age library is used.

"""

import sys
import argparse
import hashlib
import hmac as hmac_mod
import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


# ─── Bech32 (BIP-173 style, no length limit) ─────────────────

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_decode(bech_str):
    """Decode a Bech32 string → (hrp, data_bytes).  Raises on error."""
    lowered = bech_str.strip().lower()
    pos = lowered.rfind("1")
    if pos < 1:
        raise ValueError("bech32: no separator")
    hrp = lowered[:pos]
    data5 = []
    for ch in lowered[pos + 1 :]:
        idx = BECH32_CHARSET.find(ch)
        if idx < 0:
            raise ValueError(f"bech32: invalid char {ch!r}")
        data5.append(idx)
    if _bech32_polymod(_bech32_hrp_expand(hrp) + data5) != 1:
        raise ValueError("bech32: checksum failed")
    data5 = data5[:-6]  # strip 6-value checksum
    # 5-bit → 8-bit conversion (no padding)
    acc, bits, out = 0, 0, []
    for v in data5:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if bits >= 5 or ((acc << (8 - bits)) & 0xFF):
        raise ValueError("bech32: non-zero padding")
    return hrp, bytes(out)


# ─── Base64 (unpadded / "raw") ───────────────────────────────


def _b64dec(s):
    return base64.b64decode(s + "=" * (-len(s) % 4))


# ─── Header parser ───────────────────────────────────────────


def parse_header(data):
    """
    Parse the age v1 textual header from raw file bytes.

    Returns
    -------
    payload_offset : int          – byte offset where the binary payload begins
    stanzas        : list[dict]   – [{type, args, body}, ...]
    mac_bytes      : bytes        – decoded header MAC (32 bytes)
    header_for_mac : bytes        – header bytes covered by the MAC
    """
    pos = 0
    lines = []
    while pos < len(data):
        nl = data.index(b"\n", pos)
        lines.append(data[pos:nl])
        pos = nl + 1
        if lines[-1].startswith(b"--- "):
            break

    payload_offset = pos

    # ── version ──
    if lines[0] != b"age-encryption.org/v1":
        raise ValueError(f"unsupported version: {lines[0]!r}")

    # ── stanzas + MAC ──
    stanzas = []
    mac_bytes = None
    i = 1
    while i < len(lines):
        line = lines[i]

        # End line
        if line.startswith(b"--- "):
            mac_bytes = _b64dec(line[4:].decode("ascii"))
            break

        # Stanza argument line
        if not line.startswith(b"-> "):
            raise ValueError(f"unexpected header line: {line!r}")
        parts = line[3:].decode("ascii").split(" ")
        stype, sargs = parts[0], parts[1:]

        # Body lines: every line of exactly 64 base64 chars is a continuation;
        # the first line shorter than 64 chars terminates the body.
        body_parts = []
        i += 1
        while i < len(lines):
            bline = lines[i]
            if bline.startswith(b"-> ") or bline.startswith(b"--- "):
                break
            body_parts.append(bline.decode("ascii"))
            i += 1
            if len(bline) < 64:
                break

        body = _b64dec("".join(body_parts))
        stanzas.append({"type": stype, "args": sargs, "body": body})
        continue  # i already advanced past the body

    if mac_bytes is None:
        raise ValueError("missing header MAC")

    # header_for_mac = everything up to and including "---" (before the space)
    end_idx = data.index(b"\n--- ", 0, payload_offset)
    header_for_mac = data[: end_idx + 4]  # includes "\n---"

    return payload_offset, stanzas, mac_bytes, header_for_mac


# ─── X25519 file-key unwrap ──────────────────────────────────


def unwrap_x25519(stanza, identity_bytes):
    """Try to unwrap a file key from an X25519 stanza.  Returns 16-byte file
    key, or *None* if the stanza was addressed to a different recipient."""
    if stanza["type"] != "X25519":
        return None
    if len(stanza["args"]) != 1:
        raise ValueError("X25519 stanza: expected exactly 1 argument")

    ephemeral_share = _b64dec(stanza["args"][0])
    if len(ephemeral_share) != 32:
        raise ValueError("X25519 stanza: ephemeral share must be 32 bytes")
    if len(stanza["body"]) != 32:
        raise ValueError("X25519 stanza: body must be 32 bytes")

    priv = X25519PrivateKey.from_private_bytes(identity_bytes)
    peer = X25519PublicKey.from_public_bytes(ephemeral_share)
    shared = priv.exchange(peer)

    if shared == b"\x00" * 32:
        raise ValueError("X25519: all-zero shared secret")

    recipient = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    salt = ephemeral_share + recipient
    wrap_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"age-encryption.org/v1/X25519",
    ).derive(shared)

    aead = ChaCha20Poly1305(wrap_key)
    try:
        return aead.decrypt(b"\x00" * 12, stanza["body"], b"")
    except Exception:
        return None


# ─── Header MAC verification ─────────────────────────────────


def verify_mac(file_key, header_for_mac, expected_mac):
    hmac_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=b"header",
    ).derive(file_key)

    computed = hmac_mod.new(hmac_key, header_for_mac, hashlib.sha256).digest()
    if not hmac_mod.compare_digest(computed, expected_mac):
        raise ValueError("header MAC mismatch")


# ─── STREAM payload decryption ────────────────────────────────

CHUNK_PLAIN = 65536  # 64 KiB
TAG_LEN = 16  # Poly1305 tag


def decrypt_payload(file_key, payload):
    """Decrypt the age STREAM payload."""
    if len(payload) < 16:
        raise ValueError("payload too short (missing nonce)")

    nonce = payload[:16]
    ct = payload[16:]

    payload_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=nonce,
        info=b"payload",
    ).derive(file_key)

    aead = ChaCha20Poly1305(payload_key)
    enc_chunk_max = CHUNK_PLAIN + TAG_LEN

    out = bytearray()
    off = 0
    counter = 0

    while off < len(ct):
        remaining = len(ct) - off
        is_last = remaining <= enc_chunk_max
        chunk = ct[off:] if is_last else ct[off : off + enc_chunk_max]

        # 12-byte nonce: 11-byte big-endian counter ‖ 1-byte final flag
        chunk_nonce = counter.to_bytes(11, "big") + (b"\x01" if is_last else b"\x00")

        out.extend(aead.decrypt(chunk_nonce, bytes(chunk), b""))
        counter += 1
        off += len(chunk)

    return bytes(out)


# ─── CLI entry point ─────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="age v1 X25519 decryptor")
    ap.add_argument("--identity", "-i", required=True, help="Identity file")
    ap.add_argument("encrypted_file", help="Encrypted age file")
    args = ap.parse_args()

    # ── read identity ──
    identity_bytes = None
    with open(args.identity) as fh:
        for raw_line in fh:
            stripped = raw_line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.upper().startswith("AGE-SECRET-KEY-"):
                hrp, identity_bytes = bech32_decode(stripped)
                if hrp != "age-secret-key-":
                    print(f"unexpected HRP: {hrp}", file=sys.stderr)
                    sys.exit(1)
                break
    if identity_bytes is None or len(identity_bytes) != 32:
        print("no valid identity found in file", file=sys.stderr)
        sys.exit(1)

    # ── read encrypted file ──
    with open(args.encrypted_file, "rb") as fh:
        data = fh.read()

    # ── parse header ──
    payload_off, stanzas, mac, hdr_for_mac = parse_header(data)

    # ── unwrap file key ──
    file_key = None
    for st in stanzas:
        if st["type"] == "X25519":
            file_key = unwrap_x25519(st, identity_bytes)
            if file_key is not None:
                break
    if file_key is None:
        print("no matching X25519 recipient", file=sys.stderr)
        sys.exit(1)

    # ── verify header MAC ──
    try:
        verify_mac(file_key, hdr_for_mac, mac)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # ── decrypt payload ──
    try:
        plaintext = decrypt_payload(file_key, data[payload_off:])
    except Exception as exc:
        print(f"payload decryption failed: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.buffer.write(plaintext)


if __name__ == "__main__":
    main()
