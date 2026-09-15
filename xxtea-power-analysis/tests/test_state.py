
"""Tests for side-channel key recovery task."""

import os
import subprocess


def test_recovered_key_exists():
    """The agent must create /app/recovered_key.hex."""
    assert os.path.isfile('/app/recovered_key.hex'), \
        "File /app/recovered_key.hex not found"


def test_recovered_key_format():
    """The file must contain a valid 32-character hex string."""
    with open('/app/recovered_key.hex', 'r') as f:
        key_hex = f.read().strip()
    assert len(key_hex) == 32, \
        f"Expected 32 hex characters, got {len(key_hex)}"
    assert all(c in '0123456789abcdefABCDEF' for c in key_hex), \
        "Key contains non-hex characters"


def test_recovered_key_correct():
    """The recovered key must match the secret key embedded in /app/verify."""
    with open('/app/recovered_key.hex', 'r') as f:
        key_hex = f.read().strip().lower()
    result = subprocess.run(
        ['/app/verify', key_hex],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, \
        f"Verify binary exited with code {result.returncode}"
    assert result.stdout.strip() == "CORRECT", \
        f"Key verification failed: {result.stdout.strip()}"


def test_decrypted_report_exists():
    """The agent must decrypt the report to /app/decrypted_report.txt."""
    assert os.path.isfile('/app/decrypted_report.txt'), \
        "File /app/decrypted_report.txt not found"


def test_decrypted_report_content():
    """The decrypted report must contain the expected verification tokens."""
    with open('/app/decrypted_report.txt', 'r') as f:
        content = f.read()
    assert 'XXTEA_CPA_VERIFIED_OK' in content, \
        "Verification token not found in decrypted report"
    assert 'SIDE-CHANNEL ANALYSIS REPORT' in content, \
        "Report header not found in decrypted report"
