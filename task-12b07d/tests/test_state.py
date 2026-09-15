
import subprocess
import os
import struct
import pytest

EXPECTED_SECRET = "d34db33fc4f3b4b313374242f33dfac3abcdef01234567899abcdef011223344"
PARSER = "/app/fw_parser"
EXPLOIT = "/app/exploit.sb2"
REPORT = "/app/vulnerability_report.txt"


def run_parser():
    """Run the parser binary with the exploit file."""
    result = subprocess.run(
        [PARSER, EXPLOIT],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result


class TestExploitFile:
    def test_exploit_file_exists(self):
        assert os.path.isfile(EXPLOIT), f"Exploit file not found at {EXPLOIT}"

    def test_exploit_has_sb2_magic(self):
        with open(EXPLOIT, "rb") as f:
            data = f.read(4)
        assert len(data) == 4, "Exploit file is too small to contain magic"
        magic = struct.unpack("<I", data)[0]
        assert magic == 0x53423221, f"Invalid SB2 magic: 0x{magic:08x}"

    def test_exploit_minimum_size(self):
        size = os.path.getsize(EXPLOIT)
        assert size >= 140, (
            f"Exploit file is only {size} bytes; must be large enough to "
            "overflow the header buffer and reach the security bypass field"
        )


class TestExploitExecution:
    def test_parser_returns_success(self):
        r = run_parser()
        assert r.returncode == 0, (
            f"Parser returned non-zero ({r.returncode}). "
            f"stderr: {r.stderr.strip()}"
        )

    def test_authentication_bypassed(self):
        r = run_parser()
        assert "Auth required: 0" in r.stdout, (
            f"Authentication was not bypassed. Parser output:\n{r.stdout}"
        )

    def test_security_bypass_active(self):
        r = run_parser()
        assert "BYPASS_ACTIVE" in r.stdout, (
            f"Security bypass not triggered. Parser output:\n{r.stdout}"
        )

    def test_device_secret_extracted(self):
        r = run_parser()
        expected_line = f"DEVICE_SECRET:{EXPECTED_SECRET}"
        assert expected_line in r.stdout, (
            f"Device secret not correctly extracted.\n"
            f"Expected: {expected_line}\n"
            f"Parser output:\n{r.stdout}"
        )

    def test_debug_interface_enabled(self):
        r = run_parser()
        assert "DEBUG_ENABLED" in r.stdout, (
            f"Debug interface not enabled. Parser output:\n{r.stdout}"
        )


class TestVulnerabilityReport:
    def test_report_exists(self):
        assert os.path.isfile(REPORT), f"Vulnerability report not found at {REPORT}"

    def test_report_has_substance(self):
        with open(REPORT) as f:
            content = f.read()
        assert len(content) >= 300, (
            f"Report is only {len(content)} characters; expected a substantive "
            "analysis of at least 300 characters"
        )

    def test_report_identifies_overflow(self):
        with open(REPORT) as f:
            text = f.read().lower()
        overflow_terms = [
            "buffer overflow",
            "heap overflow",
            "out-of-bounds",
            "out of bounds",
            "overflow",
            "overrun",
        ]
        assert any(t in text for t in overflow_terms), (
            "Report must describe the buffer overflow / out-of-bounds write"
        )

    def test_report_identifies_attack_vector_field(self):
        with open(REPORT) as f:
            text = f.read().lower()
        assert "key_blob" in text or "key blob" in text or "keyblob" in text, (
            "Report must identify key_blob_block as the attacker-controlled field"
        )

    def test_report_explains_auth_bypass_timing(self):
        with open(REPORT) as f:
            text = f.read().lower()
        bypass_indicators = [
            "before auth",
            "before signature",
            "before verif",
            "pre-auth",
            "precedes",
            "prior to auth",
            "prior to sign",
            "prior to verif",
            "skip",
            "bypass",
            "disabled",
            "overwrite",
            "overwritten",
        ]
        assert any(t in text for t in bypass_indicators), (
            "Report must explain how authentication is bypassed "
            "(overflow occurs before signature verification)"
        )
