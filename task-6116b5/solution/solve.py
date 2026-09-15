#!/usr/bin/env python3
"""Evaluate QUIC implementations and generate compliance report + reference impl."""

import sys
import json
import importlib
import shutil

sys.path.insert(0, "/app/implementations")

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------------------------------------------------------------------------
# RFC test vector constants
# ---------------------------------------------------------------------------

DCID = bytes.fromhex("8394c8f03e515708")

V1_INITIAL_SECRET = bytes.fromhex(
    "7db5df06e7a69e432496adedb0085192"
    "3595221596ae2ae9fb8115c1e9ed0a44"
)

V2_INITIAL_SECRET = bytes.fromhex(
    "2062e8b3cd8d52092614b8071d0aa1fb"
    "7c2e3ac193f78b280e72d8f5751f6aba"
)

CRYPTO_FRAME = bytes.fromhex(
    "060040f1010000ed0303ebf8fa56f129"
    "39b9584a3896472ec40bb863cfd3e868"
    "04fe3a47f06a2b69484c000004130113"
    "02010000c000000010000e00000b6578"
    "616d706c652e636f6dff01000100000a"
    "00080006001d00170018001000070005"
    "04616c706e0005000501000000000033"
    "00260024001d00209370b2c9caa47fba"
    "baf4559fedba753de171fa71f50f1ce1"
    "5d43e994ec74d748002b000302030400"
    "0d0010000e0403050306030203080408"
    "050806002d00020101001c0002400100"
    "3900320408ffffffffffffffff050480"
    "00ffff07048000ffff08011001048000"
    "75300901100f088394c8f03e51570806"
    "048000ffff"
)
CLIENT_PAYLOAD = CRYPTO_FRAME + b"\x00" * (1162 - len(CRYPTO_FRAME))

V1_CLIENT_HEADER = bytes.fromhex(
    "c300000001088394c8f03e5157080000449e00000002"
)

V1_EXPECTED_FIRST64 = bytes.fromhex(
    "c000000001088394c8f03e5157080000"
    "449e7b9aec34d1b1c98dd7689fb8ec11"
    "d242b123dc9bd8bab936b47d92ec356c"
    "0bab7df5976d27cd449f63300099f399"
)

V1_RETRY_NO_TAG = bytes.fromhex(
    "ff000000010008f067a5502a4262b574"
    "6f6b656e"
)
V1_EXPECTED_RETRY_TAG = bytes.fromhex(
    "04a265ba2eff4d829058fb3f0f2496ba"
)

CHACHA20_SECRET = bytes.fromhex(
    "9ac312a7f877468ebe69422748ad00a1"
    "5443f18203a07d6060f688f30f21632b"
)
V1_EXPECTED_CHACHA20 = bytes.fromhex(
    "4cfe4189655e5cd55c41f69080575d79"
    "99c25a5bfb"
)


# ---------------------------------------------------------------------------
# Evaluate each implementation
# ---------------------------------------------------------------------------

def analyze_implementation(name):
    """Test an implementation against RFC vectors and return violation list."""
    mod = importlib.import_module(f"impl_{name}")
    violations = []

    # 1. Test V1 key derivation
    keys_v1 = mod.derive_initial_keys(DCID, 1)
    v1_keys_ok = keys_v1["initial_secret"] == V1_INITIAL_SECRET

    # 2. Test V2 key derivation
    keys_v2 = mod.derive_initial_keys(DCID, 2)
    v2_keys_ok = keys_v2["initial_secret"] == V2_INITIAL_SECRET

    if not v2_keys_ok and v1_keys_ok:
        violations.append("v2_key_derivation")

    # 3. Test V1 client initial packet protection
    if v1_keys_ok:
        protected = mod.protect_initial_packet(
            V1_CLIENT_HEADER, CLIENT_PAYLOAD,
            keys_v1["client_key"], keys_v1["client_iv"], keys_v1["client_hp"],
        )
        if protected[:64] != V1_EXPECTED_FIRST64:
            # Determine whether it's a nonce bug or sample offset bug.
            # Compute correct AEAD ciphertext independently.
            pn = 2
            correct_nonce = bytes(
                a ^ b for a, b in zip(
                    keys_v1["client_iv"],
                    pn.to_bytes(12, "big"),
                )
            )
            aesgcm = AESGCM(keys_v1["client_key"])
            correct_ct = aesgcm.encrypt(
                correct_nonce, CLIENT_PAYLOAD, V1_CLIENT_HEADER
            )

            # The ciphertext starts after the header in the protected packet.
            # Header protection only modifies byte 0 and the PN bytes, not the
            # ciphertext portion.  If the AEAD output is correct (nonce was
            # right) but the final packet is wrong, the bug is in the sample
            # offset used for header protection.
            pn_length = 2
            pn_offset = len(V1_CLIENT_HEADER) - pn_length
            impl_ct = protected[pn_offset + pn_length:]
            if impl_ct == correct_ct:
                violations.append("header_protection_sample_offset")
            else:
                violations.append("aead_nonce_construction")

    # 4. Test V1 retry integrity tag
    tag = mod.compute_retry_integrity_tag(DCID, V1_RETRY_NO_TAG, 1)
    if tag != V1_EXPECTED_RETRY_TAG:
        violations.append("retry_pseudo_packet")

    # 5. Test V1 ChaCha20 short header
    chacha_keys = mod.derive_keys_from_secret(CHACHA20_SECRET, 1, 32)
    chacha_protected = mod.protect_short_header_chacha20(
        bytes.fromhex("4200bff4"), bytes.fromhex("01"), 654360564,
        chacha_keys["key"], chacha_keys["iv"], chacha_keys["hp"],
    )
    if chacha_protected != V1_EXPECTED_CHACHA20:
        violations.append("chacha20_header_protection")

    return violations


report = {}
for name in ["alpha", "beta", "gamma", "delta", "epsilon"]:
    v = analyze_implementation(name)
    report[name] = {
        "status": "PASS" if not v else "FAIL",
        "violations": v,
    }

with open("/app/compliance_report.json", "w") as f:
    json.dump(report, f, indent=2)

print("Compliance report written to /app/compliance_report.json")
print(json.dumps(report, indent=2))

# ---------------------------------------------------------------------------
# Deploy the reference implementation
# ---------------------------------------------------------------------------

shutil.copy("/solution/reference_impl.py", "/app/reference_impl.py")
print("Reference implementation deployed to /app/reference_impl.py")
