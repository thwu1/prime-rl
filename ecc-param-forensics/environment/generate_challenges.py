#!/usr/bin/env python3
"""Generate challenge data for ECC implementation conformance audit task."""

import json
import hashlib
import os


def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def modinv(a, m):
    a = a % m
    g, x, _ = extended_gcd(a, m)
    if g != 1:
        raise ValueError("Modular inverse does not exist")
    return x % m


def compute_montgomery_correct(prime, wlen=64):
    """Compute correct Montgomery representation parameters."""
    bitlen = prime.bit_length()
    pbitlen = ((bitlen + wlen - 1) // wlen) * wlen
    r = pow(2, pbitlen, prime)
    r_square = pow(2, 2 * pbitlen, prime)
    p_low = prime % (2**wlen)
    mpinv = (2**wlen - modinv(p_low, 2**wlen)) % (2**wlen)
    return r, r_square, mpinv, pbitlen


def main():
    os.makedirs("/app/data", exist_ok=True)

    # ============================================================
    # CHALLENGE 1: Montgomery Representation Parameter Audit
    # ============================================================

    curves = [
        ("SECP192R1",
         0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFFFFFFFFFFFF),
        ("SECP256K1",
         0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F),
        ("FRP256V1",
         0xF1FD178C0B3AD58F10126DE8CE42435B3961ADBCABC8CA6DE8FCF353D86E9C03),
        ("SECP521R1",
         0x01FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF),
        ("BRAINPOOLP256R1",
         0xA9FB57DBA1EEA9BC3E660A909D838D726E3BF623D52620282013481D1F6E5377),
    ]

    challenge1 = {
        "description": (
            "Montgomery representation parameter audit. "
            "Word size (wlen) = 64 bits. For each curve, verify whether the "
            "given Montgomery parameters are correct for the stated prime."
        ),
        "wlen": 64,
        "curves": {}
    }

    for name, prime in curves:
        r_c, r_sq_c, mpinv_c, pbitlen_c = compute_montgomery_correct(prime)

        if name == "FRP256V1":
            # Bug: forgot to negate the modular inverse
            p_low = prime % (2**64)
            wrong_mpinv = modinv(p_low, 2**64)
            challenge1["curves"][name] = {
                "prime": hex(prime),
                "alleged_r": hex(r_c),
                "alleged_r_square": hex(r_sq_c),
                "alleged_mpinv": hex(wrong_mpinv),
                "alleged_pbitlen": pbitlen_c,
            }
        elif name == "SECP521R1":
            # Bug: used p.bit_length() directly instead of rounding up
            wrong_pbitlen = prime.bit_length()  # 521 instead of 576
            wrong_r = pow(2, wrong_pbitlen, prime)
            wrong_r_sq = pow(2, 2 * wrong_pbitlen, prime)
            challenge1["curves"][name] = {
                "prime": hex(prime),
                "alleged_r": hex(wrong_r),
                "alleged_r_square": hex(wrong_r_sq),
                "alleged_mpinv": hex(mpinv_c),
                "alleged_pbitlen": wrong_pbitlen,
            }
        else:
            challenge1["curves"][name] = {
                "prime": hex(prime),
                "alleged_r": hex(r_c),
                "alleged_r_square": hex(r_sq_c),
                "alleged_mpinv": hex(mpinv_c),
                "alleged_pbitlen": pbitlen_c,
            }

    with open("/app/data/montgomery_challenge.json", "w") as f:
        json.dump(challenge1, f, indent=2)

    # ============================================================
    # CHALLENGE 2: ECRDSA Endianness Classification
    # ============================================================

    # GOST R 34.10-2012 256-bit ParamSetA curve order
    gost256_q = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF6C611070995AD10045841B09B761B893

    # Private key (audit scenario: key is known to the auditor)
    x_priv = 0x7A1C8A51B28D36F12F9B86EB7B7B2E07CE04A4BE08DC2B8E5BB55C3B2C2F8E09 % gost256_q

    # Message and hash
    message = b"GOST R 34.10-2012 test message for ECRDSA endianness audit"
    h = hashlib.sha256(message).digest()
    h_hex = h.hex()

    # Hash interpreted in both endianness modes
    h_int_be = int.from_bytes(h, 'big')
    h_int_le = int.from_bytes(h[::-1], 'big')

    e_iso = h_int_be % gost256_q
    e_rfc = h_int_le % gost256_q

    # Fixed nonces and r values for 4 signatures
    nonces = [
        0x3C45B2A1D7E8F392A6B5C4D3E2F10987654321ABCDEF0123456789ABCDEF0123 % gost256_q,
        0x5F6E7D8C9B0A1F2E3D4C5B6A7F8E9D0C1B2A3F4E5D6C7B8A9F0E1D2C3B4A5F % gost256_q,
        0x1A2B3C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F9A0B1C2D3E4F5A6B7C8D9E0F1A % gost256_q,
        0x9F8E7D6C5B4A3F2E1D0C9B8A7F6E5D4C3B2A1F0E9D8C7B6A5F4E3D2C1B0A9F % gost256_q,
    ]

    r_vals = [
        0x2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D0E2F4A6B8C0D2E4F6A8B0C2D4E6F8A1B % gost256_q,
        0x8A7B6C5D4E3F2A1B0C9D8E7F6A5B4C3D2E1F0A9B8C7D6E5F4A3B2C1D0E9F8A % gost256_q,
        0x4F5E6D7C8B9A0F1E2D3C4B5A6F7E8D9C0B1A2F3E4D5C6B7A8F9E0D1C2B3A4F % gost256_q,
        0x1C2D3E4F5A6B7C8D9E0F1A2B3C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F9A0B1C % gost256_q,
    ]

    # Signature endianness modes: alternating ISO and RFC
    modes = ["ISO", "RFC", "RFC", "ISO"]

    ecrdsa_challenge = {
        "description": (
            "ECRDSA signature audit data. Four signatures on the same message "
            "with known private key and nonces. Each was produced under either "
            "ISO 14888-3 or RFC 7091 conventions. Classify each signature."
        ),
        "curve_order_q": hex(gost256_q),
        "private_key_x": hex(x_priv),
        "message": message.decode('ascii'),
        "message_hex": message.hex(),
        "hash_sha256_hex": h_hex,
        "signatures": []
    }

    for i in range(4):
        mode = modes[i]
        k = nonces[i]
        r_sig = r_vals[i]
        e = e_iso if mode == "ISO" else e_rfc
        s = (r_sig * x_priv + k * e) % gost256_q
        ecrdsa_challenge["signatures"].append({
            "id": "sig_%d" % (i + 1),
            "r": hex(r_sig),
            "s": hex(s),
            "k": hex(k),
        })

    with open("/app/data/ecrdsa_challenge.json", "w") as f:
        json.dump(ecrdsa_challenge, f, indent=2)

    # ============================================================
    # CHALLENGE 3: ECDSA Signature Analysis
    # ============================================================

    secp256k1_q = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

    # Private key (the target to recover)
    x_ecdsa = 0x4B7A9E3F2C1D8E6F5A0B9C8D7E6F5A4B3C2D1E0F9A8B7C6D5E4F3A2B1C0D9E % secp256k1_q

    # Shared nonce (vulnerability)
    k_shared = 0x6E5F4D3C2B1A0F9E8D7C6B5A4F3E2D1C0B9A8F7E6D5C4B3A2F1E0D9C8B7A6F % secp256k1_q

    # Two distinct messages
    m1 = b"Payment: 1000 BTC from alice to bob ref:TX001"
    m2 = b"Payment: 500 BTC from alice to charlie ref:TX002"

    e1 = int.from_bytes(hashlib.sha256(m1).digest(), 'big') % secp256k1_q
    e2 = int.from_bytes(hashlib.sha256(m2).digest(), 'big') % secp256k1_q

    # Synthetic r value
    r_ecdsa = 0x8B7A6C5D4E3F2A1B0C9D8E7F6A5B4C3D2E1F0A9B8C7D6E5F4A3B2C1D0E9F8A % secp256k1_q

    k_inv = modinv(k_shared, secp256k1_q)
    s1 = (k_inv * (e1 + x_ecdsa * r_ecdsa)) % secp256k1_q
    s2 = (k_inv * (e2 + x_ecdsa * r_ecdsa)) % secp256k1_q

    ecdsa_challenge = {
        "description": (
            "Two ECDSA signatures on different messages on SECP256K1. "
            "Investigate for cryptographic weaknesses."
        ),
        "curve_order_q": hex(secp256k1_q),
        "signature_1": {
            "message_hex": m1.hex(),
            "e": hex(e1),
            "r": hex(r_ecdsa),
            "s": hex(s1),
        },
        "signature_2": {
            "message_hex": m2.hex(),
            "e": hex(e2),
            "r": hex(r_ecdsa),
            "s": hex(s2),
        },
    }

    with open("/app/data/ecdsa_signatures.json", "w") as f:
        json.dump(ecdsa_challenge, f, indent=2)

    print("All challenge data generated successfully.")


if __name__ == "__main__":
    main()
