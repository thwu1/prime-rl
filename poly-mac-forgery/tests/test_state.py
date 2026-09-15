"""

Verification tests for polynomial MAC forgery task.
Independently computes the expected tag using hardcoded secret key.
"""

import struct
import os
import pytest


# ===== Embedded crypto for independent verification =====

def _tea_encrypt(v, key):
    v0, v1 = struct.unpack('>II', v)
    k = struct.unpack('>IIII', key)
    delta = 0x9E3779B9
    s = 0
    for _ in range(32):
        s = (s + delta) & 0xFFFFFFFF
        v0 = (v0 + (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xFFFFFFFF
        v1 = (v1 + (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xFFFFFFFF
    return struct.pack('>II', v0, v1)


def _gf64_mul(a, b):
    result = 0
    mask = (1 << 64) - 1
    for _ in range(64):
        if b & 1:
            result ^= a
        b >>= 1
        carry = a >> 63
        a = (a << 1) & mask
        if carry:
            a ^= 0x1B
    return result


def _compute_mac(ct_bytes, h, s):
    blocks = []
    for i in range(0, len(ct_bytes), 8):
        blocks.append(int.from_bytes(ct_bytes[i:i + 8], 'big'))
    acc = 0
    for block in blocks:
        acc = _gf64_mul(acc ^ block, h)
    return acc ^ s


def _derive_keys(nonce, key):
    h_bytes = _tea_encrypt(nonce, key)
    s_nonce = bytes([b ^ 0xFF for b in nonce])
    s_bytes = _tea_encrypt(s_nonce, key)
    return int.from_bytes(h_bytes, 'big'), int.from_bytes(s_bytes, 'big')


# Secret key (not present anywhere in the Docker image)
_K = bytes.fromhex("a3b1c2d4e5f60718293a4b5c6d7e8f90")

# Target parameters (hardcoded for deterministic verification)
_TARGET_CT_HEX = ("70f4e974aeb9176ace932eb7c91cc9c5"
                  "315bb8a0672b63affe59fb8948f07fdb"
                  "a96b19d6a818842b")
_TARGET_NONCE_HEX = "0011223344556677"


class TestMACForgery:
    """Verify the agent produced a valid forged authentication tag."""

    def _compute_expected_tag(self):
        ct = bytes.fromhex(_TARGET_CT_HEX)
        nonce = bytes.fromhex(_TARGET_NONCE_HEX)
        h, s = _derive_keys(nonce, _K)
        return format(_compute_mac(ct, h, s), '016x')

    def test_output_file_exists(self):
        assert os.path.isfile("/app/output/forged_tag.txt"), \
            "Output file /app/output/forged_tag.txt does not exist"

    def test_output_format(self):
        with open("/app/output/forged_tag.txt") as f:
            tag = f.read().strip()
        assert len(tag) == 16, \
            f"Tag must be 16 hex characters, got {len(tag)}"
        assert all(c in "0123456789abcdef" for c in tag), \
            "Tag must be lowercase hex"

    def test_forged_tag_is_correct(self):
        expected = self._compute_expected_tag()
        with open("/app/output/forged_tag.txt") as f:
            actual = f.read().strip()
        assert actual == expected, \
            f"Forged tag {actual} does not match expected {expected}"

    def test_tag_verifies_independently(self):
        """Cross-check: verify the forged tag authenticates correctly."""
        ct = bytes.fromhex(_TARGET_CT_HEX)
        nonce = bytes.fromhex(_TARGET_NONCE_HEX)
        h, s = _derive_keys(nonce, _K)

        with open("/app/output/forged_tag.txt") as f:
            forged = int(f.read().strip(), 16)

        computed = _compute_mac(ct, h, s)
        assert forged == computed, \
            "Forged tag does not authenticate against the MAC scheme"
