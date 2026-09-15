
"""
Verify that the agent has:
  1. Correctly identified the server's implementation variant.
  2. Provided a meaningful security assessment.
  3. Forged a valid authenticator for the target message.
"""

import hashlib
import json
import os
import subprocess

import pytest

P = (1 << 130) - 5


def _le(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _to_le(n: int, length: int) -> bytes:
    return (n % (1 << (8 * length))).to_bytes(length, "little")


def _server_mac(msg: bytes, r_int: int, s_int: int) -> bytes:
    """Compute the MAC using the server's actual variant."""
    acc = 0
    for i in range(0, len(msg), 16):
        chunk = msg[i : i + 16]
        c = int.from_bytes(chunk, "big") + (1 << (8 * len(chunk)))
        acc = ((acc + c) * r_int) % P
    tag = (acc + s_int) % (1 << 128)
    return _to_le(tag, 16)


def _get_key_material():
    """Derive the secret key material used to generate the task data."""
    r_raw = hashlib.sha256(b"poly1305-nonce-reuse-task-r-key-v3").digest()[:16]
    r_c = bytearray(r_raw)
    for i in [3, 7, 11, 15]:
        r_c[i] &= 0x0F
    for i in [4, 8, 12]:
        r_c[i] &= 0xFC
    r_int = _le(bytes(r_c))
    nonce = bytes.fromhex("f0e1d2c3b4a596870718293a4b5c6d7e")
    s_int = _le(hashlib.sha256(b"poly1305-s-val-" + nonce).digest()[:16])
    return r_int, s_int


def _expected_forged_tag() -> bytes:
    r_int, s_int = _get_key_material()
    msg = bytes.fromhex("5061792045766520243939393939")
    return _server_mac(msg, r_int, s_int)


# ---- Audit report tests ----

class TestAuditReport:
    def test_audit_file_exists(self):
        assert os.path.isfile("/app/audit_report.json"), \
            "Missing /app/audit_report.json"

    def test_audit_is_valid_json(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_server_implementation_identified(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assert report.get("server_implementation") == "beta", \
            f"Expected 'beta', got '{report.get('server_implementation')}'"

    def test_implementation_deviation_described(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        desc = report.get("implementation_deviation", "")
        assert isinstance(desc, str) and len(desc) > 20, \
            "implementation_deviation must be a substantive description"

    def test_vulnerability_assessment_provided(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assessment = report.get("vulnerability_assessment", "")
        assert isinstance(assessment, str) and len(assessment) > 30, \
            "vulnerability_assessment must be a substantive evaluation"


# ---- Forged tag tests ----

class TestForgedTag:
    def test_forged_tag_file_exists(self):
        assert os.path.isfile("/app/forged_tag.hex"), \
            "Missing /app/forged_tag.hex"

    def test_forged_tag_format(self):
        with open("/app/forged_tag.hex") as f:
            content = f.read().strip()
        assert len(content) == 32, \
            f"Expected 32 hex chars, got {len(content)}"
        assert all(c in "0123456789abcdef" for c in content), \
            "Tag must be lowercase hex"

    def test_forged_tag_correct(self):
        expected = _expected_forged_tag()
        with open("/app/forged_tag.hex") as f:
            submitted_hex = f.read().strip()
        submitted = bytes.fromhex(submitted_hex)
        assert submitted == expected, \
            f"Forged tag {submitted.hex()} != expected {expected.hex()}"

    def test_forged_tag_validates_via_binary(self):
        """Cross-check: the beta binary must produce the same tag."""
        r_int, s_int = _get_key_material()
        r_hex = _to_le(r_int, 16).hex()
        s_hex = _to_le(s_int, 16).hex()
        msg_hex = "5061792045766520243939393939"

        beta_path = "/app/implementations/beta"
        if not os.path.isfile(beta_path):
            # Try building it
            subprocess.run(["make", "-C", "/app/implementations", "beta"],
                           capture_output=True, timeout=30)

        if os.path.isfile(beta_path):
            result = subprocess.run(
                [beta_path, r_hex, s_hex, msg_hex],
                capture_output=True, text=True, timeout=10
            )
            binary_tag = result.stdout.strip()
            with open("/app/forged_tag.hex") as f:
                submitted = f.read().strip()
            assert submitted == binary_tag, \
                f"Tag {submitted} doesn't match beta binary output {binary_tag}"
        else:
            pytest.skip("Beta binary not available for cross-check")
