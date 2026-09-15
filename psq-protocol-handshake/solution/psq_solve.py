#!/usr/bin/env python3

"""
PSQ Protocol Implementation — DH-Based Registration Mode
Ciphersuite: X25519_NONE_X25519_CHACHA20POLY1305_HKDFSHA256

Implements all required crypto primitives from scratch using only
Python standard library (hashlib, hmac, struct).
"""

import hmac as hmac_mod
import hashlib
import struct
import json

# ============================================================
# X25519 (RFC 7748)
# ============================================================
_P = 2**255 - 19


def _clamp(k: bytes) -> bytes:
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return bytes(k)


def _mod_inv(a: int, p: int = _P) -> int:
    return pow(a, p - 2, p)


def x25519(k_bytes: bytes, u_bytes: bytes) -> bytes:
    """X25519 scalar multiplication per RFC 7748."""
    k = int.from_bytes(_clamp(k_bytes), "little")
    u = int.from_bytes(u_bytes, "little") % _P

    x_1 = u
    x_2, z_2 = 1, 0
    x_3, z_3 = u, 1
    swap = 0

    for t in range(254, -1, -1):
        k_t = (k >> t) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t

        A = (x_2 + z_2) % _P
        AA = (A * A) % _P
        B = (x_2 - z_2) % _P
        BB = (B * B) % _P
        E = (AA - BB) % _P
        C = (x_3 + z_3) % _P
        D = (x_3 - z_3) % _P
        DA = (D * A) % _P
        CB = (C * B) % _P
        x_3 = pow(DA + CB, 2, _P)
        z_3 = (x_1 * pow(DA - CB, 2, _P)) % _P
        x_2 = (AA * BB) % _P
        z_2 = (E * ((AA + 121665 * E) % _P)) % _P

    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2

    return ((x_2 * _mod_inv(z_2)) % _P).to_bytes(32, "little")


_BASEPOINT = (9).to_bytes(32, "little")


def x25519_public_key(sk: bytes) -> bytes:
    return x25519(sk, _BASEPOINT)


def x25519_derive(sk: bytes, pk: bytes) -> bytes:
    return x25519(sk, pk)


# ============================================================
# HKDF-SHA256 (RFC 5869)
# ============================================================
def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    if not salt:
        salt = b"\x00" * 32
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int = 32) -> bytes:
    n = (length + 31) // 32
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def kdf(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """KDF(ikm, info) = HKDF-Expand(HKDF-Extract(salt=b"", ikm), info, length)"""
    prk = hkdf_extract(b"", ikm)
    return hkdf_expand(prk, info, length)


# ============================================================
# ChaCha20-Poly1305 (RFC 8439)
# ============================================================
def _rotl32(v: int, n: int) -> int:
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def _qr(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] ^= s[a]; s[d] = _rotl32(s[d], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] ^= s[c]; s[b] = _rotl32(s[b], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] ^= s[a]; s[d] = _rotl32(s[d], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] ^= s[c]; s[b] = _rotl32(s[b], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    state = [
        0x61707865, 0x3320646E, 0x79622D32, 0x6B206574,
        *struct.unpack("<4I", key[:16]),
        *struct.unpack("<4I", key[16:]),
        counter & 0xFFFFFFFF,
        *struct.unpack("<3I", nonce),
    ]
    w = list(state)
    for _ in range(10):
        _qr(w, 0, 4, 8, 12); _qr(w, 1, 5, 9, 13)
        _qr(w, 2, 6, 10, 14); _qr(w, 3, 7, 11, 15)
        _qr(w, 0, 5, 10, 15); _qr(w, 1, 6, 11, 12)
        _qr(w, 2, 7, 8, 13); _qr(w, 3, 4, 9, 14)
    return b"".join(struct.pack("<I", (w[i] + state[i]) & 0xFFFFFFFF) for i in range(16))


def _chacha20_encrypt(key: bytes, nonce: bytes, counter: int, plaintext: bytes) -> bytes:
    ct = bytearray()
    for i in range(0, len(plaintext), 64):
        block = _chacha20_block(key, counter + i // 64, nonce)
        chunk = plaintext[i : i + 64]
        ct.extend(b ^ k for b, k in zip(chunk, block[: len(chunk)]))
    return bytes(ct)


def _poly1305_clamp(r_bytes: bytes) -> int:
    r = int.from_bytes(r_bytes, "little")
    r &= 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    return r


def _poly1305_mac(key: bytes, msg: bytes) -> bytes:
    r = _poly1305_clamp(key[:16])
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        chunk = msg[i : i + 16]
        n = int.from_bytes(chunk + b"\x01", "little")
        acc = ((acc + n) * r) % p
    acc = (acc + s) & ((1 << 128) - 1)
    return acc.to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    r = len(data) % 16
    return b"\x00" * (16 - r) if r else b""


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    ciphertext = _chacha20_encrypt(key, nonce, 1, plaintext)
    mac_data = (
        aad + _pad16(aad) + ciphertext + _pad16(ciphertext)
        + struct.pack("<Q", len(aad)) + struct.pack("<Q", len(ciphertext))
    )
    tag = _poly1305_mac(poly_key, mac_data)
    return ciphertext + tag


def aead_decrypt(key: bytes, nonce: bytes, ct_tag: bytes, aad: bytes) -> bytes:
    ct, tag = ct_tag[:-16], ct_tag[-16:]
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    mac_data = (
        aad + _pad16(aad) + ct + _pad16(ct)
        + struct.pack("<Q", len(aad)) + struct.pack("<Q", len(ct))
    )
    if not hmac_mod.compare_digest(tag, _poly1305_mac(poly_key, mac_data)):
        raise ValueError("AEAD authentication failed")
    return _chacha20_encrypt(key, nonce, 1, ct)


# ============================================================
# Serialization helpers
# ============================================================
def len_prefix(data: bytes) -> bytes:
    return len(data).to_bytes(2, "big") + data


def optional(data):
    return b"\x00" if data is None else b"\x01" + data


# ============================================================
# PSQ Handshake
# ============================================================
ZERO_NONCE = b"\x00" * 12


def main():
    import os
    input_path = "/app/inputs.json"
    if not os.path.exists(input_path):
        input_path = "/data/inputs.json"
    with open(input_path, "r") as f:
        inp = json.load(f)

    priv_I = bytes.fromhex(inp["priv_I"])
    priv_R = bytes.fromhex(inp["priv_R"])
    epriv_I = bytes.fromhex(inp["epriv_I"])
    epriv_R = bytes.fromhex(inp["epriv_R"])
    context = bytes.fromhex(inp["context"])
    reg_payload = bytes.fromhex(inp["registration_payload"])
    reg_inner_aad = bytes.fromhex(inp["registration_inner_aad"])
    reg_outer_aad = bytes.fromhex(inp["registration_outer_aad"])
    resp_payload = bytes.fromhex(inp["response_payload"])
    resp_aad = bytes.fromhex(inp["response_aad"])
    psk = bytes.fromhex(inp["psk"])
    export_ctx = bytes.fromhex(inp["export_context"])

    # Compute public keys
    pub_I = x25519_public_key(priv_I)
    pub_R = x25519_public_key(priv_R)
    epub_I = x25519_public_key(epriv_I)
    epub_R = x25519_public_key(epriv_R)

    # === INITIATOR ===
    # tx0
    tx0 = hashlib.sha256(b"\x00" + len_prefix(context) + pub_R + epub_I).digest()

    # K_0
    ss_dh_outer = x25519_derive(epriv_I, pub_R)
    K_0 = kdf(ss_dh_outer, tx0)

    # tx1 (no PQ-KEM)
    tx1 = hashlib.sha256(
        b"\x01" + tx0 + pub_I + optional(None) + optional(None)
    ).digest()

    # K_1
    ss_dh_inner = x25519_derive(priv_I, pub_R)
    K_1 = kdf(K_0 + ss_dh_inner, tx1)

    # Inner encryption
    ctxt_inner = aead_encrypt(K_1, ZERO_NONCE, reg_payload, reg_inner_aad)

    # === RESPONDER ===
    # tx2
    tx2 = hashlib.sha256(b"\x02" + tx1 + epub_R).digest()

    # K_2
    ss_dh_response_1 = x25519_derive(epriv_R, pub_I)
    ss_dh_response_2 = x25519_derive(epriv_R, epub_I)
    K_2 = kdf(K_1 + ss_dh_response_1 + ss_dh_response_2, tx2)

    # === SESSION DERIVATION ===
    K_S = kdf(K_2, b"session key" + tx2)
    session_ID = kdf(K_S, b"shared key id")
    pk_binder = kdf(K_S, pub_I + pub_R)

    K_i2r_0 = kdf(K_S, b"i2r channel key" + pk_binder + (0).to_bytes(4, "big"))
    K_r2i_0 = kdf(K_S, b"r2i channel key" + pk_binder + (0).to_bytes(4, "big"))
    K_i2r_1 = kdf(K_S, b"i2r channel key" + pk_binder + (1).to_bytes(4, "big"))
    K_r2i_1 = kdf(K_S, b"r2i channel key" + pk_binder + (1).to_bytes(4, "big"))

    K_export = kdf(K_S, export_ctx + b"PSQ secret export")

    # === REKEY ===
    K_import = kdf(K_S + psk, b"secret import")
    tx_prime = hashlib.sha256(tx2 + session_ID).digest()
    K_S_prime = kdf(K_import, b"session secret" + tx_prime)
    session_ID_prime = kdf(K_S_prime, b"shared key id")

    # === OUTPUT ===
    output = {
        "intermediate": {
            "ss_dh_outer": ss_dh_outer.hex(),
            "ss_dh_inner": ss_dh_inner.hex(),
            "ss_dh_response_1": ss_dh_response_1.hex(),
            "ss_dh_response_2": ss_dh_response_2.hex(),
            "tx0": tx0.hex(),
            "tx1": tx1.hex(),
            "tx2": tx2.hex(),
            "K_0": K_0.hex(),
            "K_1": K_1.hex(),
            "K_2": K_2.hex(),
            "ctxt_inner": ctxt_inner.hex(),
        },
        "session": {
            "K_S": K_S.hex(),
            "session_ID": session_ID.hex(),
            "pk_binder": pk_binder.hex(),
            "K_i2r_0": K_i2r_0.hex(),
            "K_r2i_0": K_r2i_0.hex(),
            "K_i2r_1": K_i2r_1.hex(),
            "K_r2i_1": K_r2i_1.hex(),
            "K_export": K_export.hex(),
        },
        "rekey": {
            "K_import": K_import.hex(),
            "tx_prime": tx_prime.hex(),
            "K_S_prime": K_S_prime.hex(),
            "session_ID_prime": session_ID_prime.hex(),
        },
    }

    with open("/app/output.json", "w") as f:
        json.dump(output, f, indent=2)

    print("PSQ handshake completed successfully.")


if __name__ == "__main__":
    main()
