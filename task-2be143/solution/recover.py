#!/usr/bin/env python3
"""Recover plaintext from age v1 files with unknown protocol deviations."""
import os
import sys
import re
import glob
import hashlib
import base64
import subprocess
import hmac as _hmac

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_decode(s):
    s = s.lower()
    p = s.rfind("1")
    dp = s[p + 1 :]
    return [BECH32_CHARSET.index(c) for c in dp][:-6]


def _convertbits(data, fb, tb, pad=True):
    acc, bits, ret, mx = 0, 0, [], (1 << tb) - 1
    for v in data:
        acc = (acc << fb) | v
        bits += fb
        while bits >= tb:
            bits -= tb
            ret.append((acc >> bits) & mx)
    if pad and bits:
        ret.append((acc << (tb - bits)) & mx)
    return ret


def load_identity(path):
    """Load AGE-SECRET-KEY-... from file, return X25519PrivateKey."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.upper().startswith("AGE-SECRET-KEY-"):
                d5 = _bech32_decode(line)
                d8 = _convertbits(d5, 5, 8, pad=False)
                return X25519PrivateKey.from_private_bytes(bytes(d8[:32]))
    raise ValueError("No identity key found")


def b64d(s):
    """Decode unpadded base64."""
    return base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4))


def hkdf(ikm, salt, info, length=32):
    """HKDF-SHA-256 per RFC 5869."""
    if not salt:
        salt = b"\x00" * 32
    prk = _hmac.new(salt, ikm, hashlib.sha256).digest()
    t, okm = b"", b""
    for i in range(1, (length + 31) // 32 + 1):
        t = _hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def parse_header(data):
    """Parse age v1 header from raw file bytes.

    Returns (stanzas, mac_bytes, header_for_mac_str, payload_start).
    Each stanza is (type_str, args_list, body_bytes).
    """
    marker = b"\n--- "
    mpos = data.index(marker)
    mac_start = mpos + len(marker)
    mac_end = data.index(b"\n", mac_start)
    mac_bytes = b64d(data[mac_start:mac_end].decode())
    payload_start = mac_end + 1

    # Header for MAC: everything up to and including "---"
    header_for_mac = data[: mpos + 4].decode()

    # Parse stanza lines
    header_text = data[: mpos + 1].decode()
    lines = header_text.split("\n")
    # lines[0] = version line

    stanzas = []
    i = 1
    while i < len(lines):
        if lines[i].startswith("-> "):
            parts = lines[i][3:].split(" ")
            stype = parts[0]
            args = parts[1:]
            body_parts = []
            i += 1
            while i < len(lines):
                bl = lines[i]
                body_parts.append(bl)
                i += 1
                if len(bl) < 64:
                    break
            body = b64d("".join(body_parts))
            stanzas.append((stype, args, body))
        else:
            i += 1

    return stanzas, mac_bytes, header_for_mac, payload_start


def try_unwrap(priv_key, stanzas, salt_order, info_str):
    """Attempt to unwrap file key with given derivation parameters.

    salt_order: "standard" = eph||recip, "swapped" = recip||eph
    info_str: bytes info for HKDF
    Returns file_key (16 bytes) or None.
    """
    pub_bytes = priv_key.public_key().public_bytes_raw()

    for stype, args, body in stanzas:
        if stype != "X25519" or len(args) != 1:
            continue
        eph_bytes = b64d(args[0])
        if len(eph_bytes) != 32 or len(body) != 32:
            continue

        eph_pub = X25519PublicKey.from_public_bytes(eph_bytes)
        shared = priv_key.exchange(eph_pub)

        if all(b == 0 for b in shared):
            continue

        if salt_order == "swapped":
            salt = pub_bytes + eph_bytes
        else:
            salt = eph_bytes + pub_bytes

        wrap_key = hkdf(shared, salt, info_str)
        try:
            return ChaCha20Poly1305(wrap_key).decrypt(b"\x00" * 12, body, None)
        except Exception:
            continue
    return None


def decrypt_stream(data, payload_start, file_key, counter_endian):
    """Decrypt STREAM payload.

    counter_endian: "big" or "little" for the 11-byte chunk counter.
    Returns plaintext bytes or None on auth failure.
    """
    payload = data[payload_start:]
    nonce_prefix = payload[:16]
    ct = payload[16:]

    pkey = hkdf(file_key, nonce_prefix, b"payload")
    aead = ChaCha20Poly1305(pkey)
    chunk_ct_size = 65536 + 16  # plaintext chunk + poly1305 tag

    out = bytearray()
    off, ctr = 0, 0
    while off < len(ct):
        is_final = (len(ct) - off) <= chunk_ct_size
        chunk = ct[off : off + chunk_ct_size]

        counter_bytes = ctr.to_bytes(11, counter_endian)
        nonce = counter_bytes + (b"\x01" if is_final else b"\x00")

        try:
            out.extend(aead.decrypt(nonce, bytes(chunk), None))
        except Exception:
            return None

        off += chunk_ct_size
        ctr += 1

    return bytes(out)


def verify_mac(file_key, header_for_mac, mac_bytes):
    """Verify the header MAC using the file key."""
    mac_key = hkdf(file_key, b"", b"header")
    expected = _hmac.new(mac_key, header_for_mac.encode(), hashlib.sha256).digest()
    return _hmac.compare_digest(expected, mac_bytes)


def recover(filepath, priv_key):
    """Try all parameter combinations to recover plaintext."""
    with open(filepath, "rb") as f:
        data = f.read()

    stanzas, mac_bytes, header_for_mac, payload_start = parse_header(data)

    # Parameter space for wrap key derivation
    salt_orders = ["standard", "swapped"]
    info_strings = [
        b"age-encryption.org/v1/X25519",
        b"age-encryption.org/v1",
    ]

    for so in salt_orders:
        for info in info_strings:
            fk = try_unwrap(priv_key, stanzas, so, info)
            if fk is None:
                continue
            if not verify_mac(fk, header_for_mac, mac_bytes):
                continue
            # File key recovered and MAC verified. Try payload decryption.
            for endian in ["big", "little"]:
                pt = decrypt_stream(data, payload_start, fk, endian)
                if pt is not None:
                    return pt
    return None


def extract_token(plaintext):
    """Extract token value from decrypted plaintext."""
    text = plaintext.decode("utf-8", errors="replace")
    m = re.search(r"Token:\s*(\S+)", text)
    return m.group(1) if m else None


def main():
    priv_key = load_identity("/app/identity.key")
    tokens = []

    for fpath in sorted(glob.glob("/app/corpus/*.age")):
        # Skip files the reference CLI can decrypt
        r = subprocess.run(
            ["age", "-d", "-i", "/app/identity.key", fpath],
            capture_output=True,
        )
        if r.returncode == 0:
            continue

        pt = recover(fpath, priv_key)
        if pt is not None:
            tok = extract_token(pt)
            if tok:
                tokens.append(tok)
                print(f"Recovered from {os.path.basename(fpath)}: {tok}")
            else:
                print(f"Decrypted {os.path.basename(fpath)} but no token found")
        else:
            print(f"Failed to recover {os.path.basename(fpath)}")

    tokens.sort()
    with open("/app/recovered.txt", "w") as f:
        for t in tokens:
            f.write(t + "\n")
    print(f"Wrote {len(tokens)} tokens to /app/recovered.txt")


if __name__ == "__main__":
    main()
