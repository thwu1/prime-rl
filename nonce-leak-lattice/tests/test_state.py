
"""
Tests for verifying the recovered ECDSA private key.

Verification approach: Given a candidate private key x, reconstruct each nonce
k_i = s_i^{-1} * (h_i + x * r_i) mod q, then check that the middle 96 bits
(bit positions 80-175) match the leaked values. All 30 signatures must match.
"""

import json
import os
import pytest


Q = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
MID_MASK = (1 << 96) - 1
MID_SHIFT = 80


def load_data():
    with open("/app/data.json") as f:
        return json.load(f)


def load_recovered_key():
    path = "/app/secret_key.txt"
    if not os.path.exists(path):
        pytest.fail("File /app/secret_key.txt does not exist")
    with open(path) as f:
        raw = f.read().strip()
    try:
        x = int(raw, 16)
    except ValueError:
        pytest.fail(f"Could not parse key as hex: {raw!r}")
    return x


def reconstruct_nonce(x, r_i, s_i, h_i, q):
    """Reconstruct nonce k_i from the private key and signature values."""
    s_inv = pow(s_i, q - 2, q)
    k_i = (s_inv * ((h_i + x * r_i) % q)) % q
    return k_i


class TestKeyRecovery:

    @pytest.fixture(scope="class")
    def data(self):
        return load_data()

    @pytest.fixture(scope="class")
    def recovered_key(self):
        return load_recovered_key()

    def test_key_file_exists(self):
        assert os.path.exists("/app/secret_key.txt"), \
            "secret_key.txt must exist at /app/secret_key.txt"

    def test_key_is_valid_hex(self, recovered_key):
        assert 0 < recovered_key < Q, \
            f"Key must be in range (0, q), got {hex(recovered_key)}"

    def test_all_signatures_verify(self, data, recovered_key):
        """
        Core verification: for every signature, the reconstructed nonce
        must have middle bits matching the leaked value.
        """
        x = recovered_key
        q = int(data["q"], 16)
        assert q == Q

        failures = []
        for sig in data["signatures"]:
            idx = sig["index"]
            r_i = int(sig["r"], 16)
            s_i = int(sig["s"], 16)
            h_i = int(sig["h"], 16)
            leaked_mid = int(sig["leaked_mid"], 16)

            k_i = reconstruct_nonce(x, r_i, s_i, h_i, q)
            mid_bits = (k_i >> MID_SHIFT) & MID_MASK

            if mid_bits != leaked_mid:
                failures.append(idx)

        assert len(failures) == 0, \
            f"Nonce middle-bit mismatch on signature indices: {failures}"

    def test_minimum_signature_count(self, data):
        """Ensure data has at least 10 signatures for robust verification."""
        assert len(data["signatures"]) >= 10

    def test_key_not_trivial(self, recovered_key):
        """Reject trivially wrong keys."""
        assert recovered_key != 0
        assert recovered_key != 1
        assert recovered_key != Q - 1
