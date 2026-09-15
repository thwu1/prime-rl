
"""
Tests for the TweetNaCl forensic audit task.
Verifies:
1. The plaintext file exists and matches expected content.
2. The fixed tweetnacl.c compiles and produces correct output for all test vectors.
3. The forgery PoC compiles, runs, and demonstrates MAC divergence.
4. The bug report has correct structure and classifications.
"""

import os
import subprocess
import tempfile
import shutil
import json
import pytest

EXPECTED_PLAINTEXT = "The Poly1305-AES message-authentication code by Daniel J. Bernstein provides provable security."

EXPECTED_SALSA20 = "a09b7719223218a8fba5a33dbf01a53803878d3ac61d33fb3efa6c702c95d38d4d2291cf4bda507e3b87b81a12db25ac7b6f812cab7daee17bed3d88a8afbb94"
EXPECTED_HSALSA20 = "5b35853e5d47f5d6606ec6cba9a155888bb872d136913d5fa79dfdb4bfd1a375"
EXPECTED_POLY1305 = "7f943f45cd8fdac2bf70dc986ddd0446"
EXPECTED_CURVE25519 = "1c9fd88f45606d932a80c71824ae151d15d73e77de38e8e000852e614fae7019"

TEST_HARNESS_C = r'''
#include <stdio.h>
#include <string.h>
#include "tweetnacl.h"

void randombytes(unsigned char *x, unsigned long long xlen) {
    unsigned long long i;
    for (i = 0; i < xlen; i++) x[i] = 0;
}

static void print_hex(const unsigned char *data, int len) {
    for (int i = 0; i < len; i++) printf("%02x", data[i]);
    printf("\n");
}

int main(void) {
    /* Test 1: Salsa20 core */
    {
        unsigned char out[64];
        unsigned char k[32] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,
                               201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216};
        unsigned char in[16] = {101,102,103,104,105,106,107,108,0,0,0,0,0,0,0,0};
        unsigned char c[16] = "expand 32-byte k";
        crypto_core_salsa20(out, in, k, c);
        printf("SALSA20=");
        print_hex(out, 64);
    }

    /* Test 2: HSalsa20 */
    {
        unsigned char out[32];
        unsigned char k[32], in[16];
        unsigned char c[16] = "expand 32-byte k";
        for (int i = 0; i < 32; i++) k[i] = i + 50;
        for (int i = 0; i < 16; i++) in[i] = i + 100;
        crypto_core_hsalsa20(out, in, k, c);
        printf("HSALSA20=");
        print_hex(out, 32);
    }

    /* Test 3: Poly1305 (raw key - internal clamping matters) */
    {
        unsigned char out[16];
        unsigned char key[32];
        for (int i = 0; i < 32; i++) key[i] = i + 10;
        const char *msg = "Cryptographic doom principle";
        crypto_onetimeauth(out, (const unsigned char *)msg, strlen(msg), key);
        printf("POLY1305=");
        print_hex(out, 16);
    }

    /* Test 4: Curve25519 */
    {
        unsigned char result[32];
        unsigned char scalar[32] = {0xa5,0x46,0xe3,0x6b,0xf0,0x52,0x7c,0x9d,
                                    0x3b,0x16,0x15,0x4b,0x82,0x46,0x5e,0xdd,
                                    0x62,0x14,0x4c,0x0a,0xc1,0xfc,0x5a,0x18,
                                    0x50,0x6a,0x22,0x44,0xba,0x44,0x9a,0xc4};
        unsigned char bp[32] = {9};
        crypto_scalarmult(result, scalar, bp);
        printf("CURVE25519=");
        print_hex(result, 32);
    }

    /* Test 5: crypto_secretbox roundtrip */
    {
        unsigned char key[32] = {0x1b,0x27,0x55,0x64,0x73,0xe9,0x85,0xd4,
                                 0x62,0xcd,0x51,0x19,0x7a,0x9a,0x46,0xc7,
                                 0x60,0x09,0x54,0x9e,0xac,0x64,0x74,0xf2,
                                 0x06,0xc4,0xee,0x08,0x44,0xf6,0x83,0x89};
        unsigned char nonce[24] = {0x69,0x69,0x6e,0xe9,0x55,0xb6,0x2b,0x73,
                                   0xcd,0x62,0xbd,0xa8,0x75,0xfc,0x73,0xd6,
                                   0x82,0x19,0xe0,0x03,0x6b,0x7a,0x0b,0x37};
        const char *pt = "The Poly1305-AES message-authentication code by Daniel J. Bernstein provides provable security.";
        int ptlen = strlen(pt);
        int mlen = ptlen + 32;
        unsigned char m[256] = {0};
        unsigned char c[256] = {0};
        unsigned char m2[256] = {0};
        memcpy(m + 32, pt, ptlen);
        crypto_secretbox(c, m, mlen, nonce, key);
        int ret = crypto_secretbox_open(m2, c, mlen, nonce, key);
        if (ret == 0) {
            printf("ROUNDTRIP=");
            for (int i = 32; i < mlen; i++) putchar(m2[i]);
            printf("\n");
        } else {
            printf("ROUNDTRIP=FAILED\n");
        }
    }

    return 0;
}
'''

_harness_cache = None


def _get_harness_output():
    """Compile and run the test harness once, cache the result."""
    global _harness_cache
    if _harness_cache is not None:
        return _harness_cache

    tmpdir = tempfile.mkdtemp(prefix="nacl_test_")
    try:
        test_c = os.path.join(tmpdir, "test_harness.c")
        with open(test_c, "w") as f:
            f.write(TEST_HARNESS_C)

        shutil.copy("/app/tweetnacl.c", os.path.join(tmpdir, "tweetnacl.c"))
        shutil.copy("/app/tweetnacl.h", os.path.join(tmpdir, "tweetnacl.h"))

        binary = os.path.join(tmpdir, "test_harness")
        result = subprocess.run(
            ["gcc", "-o", binary, test_c, os.path.join(tmpdir, "tweetnacl.c"), "-O2"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"

        result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"Test harness crashed:\n{result.stderr}"

        output = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                output[key.strip()] = val.strip()
        _harness_cache = output
        return output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Existing tests: plaintext, test vectors, roundtrip
# ============================================================

def test_plaintext_file_exists():
    """The plaintext file must exist."""
    assert os.path.isfile("/app/plaintext.txt"), "/app/plaintext.txt does not exist"


def test_plaintext_content():
    """The decrypted plaintext must match exactly."""
    with open("/app/plaintext.txt", "r") as f:
        content = f.read()
    content = content.rstrip("\n")
    assert content == EXPECTED_PLAINTEXT, (
        f"Plaintext mismatch.\nExpected: {EXPECTED_PLAINTEXT!r}\nGot:      {content!r}"
    )


def test_salsa20_core_vector():
    """The fixed tweetnacl must produce correct Salsa20 core output."""
    output = _get_harness_output()
    assert "SALSA20" in output, "SALSA20 output not found in test harness output"
    assert output["SALSA20"] == EXPECTED_SALSA20, (
        f"Salsa20 core mismatch.\nExpected: {EXPECTED_SALSA20}\nGot:      {output['SALSA20']}"
    )


def test_hsalsa20_core_vector():
    """The fixed tweetnacl must produce correct HSalsa20 output."""
    output = _get_harness_output()
    assert "HSALSA20" in output, "HSALSA20 output not found"
    assert output["HSALSA20"] == EXPECTED_HSALSA20, (
        f"HSalsa20 mismatch.\nExpected: {EXPECTED_HSALSA20}\nGot:      {output['HSALSA20']}"
    )


def test_poly1305_vector():
    """The fixed tweetnacl must produce correct Poly1305 MAC."""
    output = _get_harness_output()
    assert "POLY1305" in output, "POLY1305 output not found"
    assert output["POLY1305"] == EXPECTED_POLY1305, (
        f"Poly1305 mismatch.\nExpected: {EXPECTED_POLY1305}\nGot:      {output['POLY1305']}"
    )


def test_curve25519_vector():
    """The fixed tweetnacl must produce correct Curve25519 scalar mult output."""
    output = _get_harness_output()
    assert "CURVE25519" in output, "CURVE25519 output not found"
    assert output["CURVE25519"] == EXPECTED_CURVE25519, (
        f"Curve25519 mismatch.\nExpected: {EXPECTED_CURVE25519}\nGot:      {output['CURVE25519']}"
    )


def test_secretbox_roundtrip():
    """The fixed tweetnacl must successfully encrypt/decrypt (roundtrip)."""
    output = _get_harness_output()
    assert "ROUNDTRIP" in output, "ROUNDTRIP output not found"
    assert output["ROUNDTRIP"] == EXPECTED_PLAINTEXT, (
        f"Secretbox roundtrip failed.\nExpected: {EXPECTED_PLAINTEXT!r}\nGot:      {output['ROUNDTRIP']!r}"
    )


# ============================================================
# Forgery PoC tests
# ============================================================

_forgery_cache = None


def _get_forgery_output():
    """Compile and run the forgery PoC once, cache the result."""
    global _forgery_cache
    if _forgery_cache is not None:
        return _forgery_cache

    assert os.path.isfile("/app/forgery_poc.c"), "/app/forgery_poc.c does not exist"

    tmpdir = tempfile.mkdtemp(prefix="forgery_test_")
    try:
        shutil.copy("/app/forgery_poc.c", os.path.join(tmpdir, "forgery_poc.c"))
        shutil.copy("/app/tweetnacl.c", os.path.join(tmpdir, "tweetnacl.c"))
        shutil.copy("/app/tweetnacl.h", os.path.join(tmpdir, "tweetnacl.h"))

        binary = os.path.join(tmpdir, "forgery_poc")
        result = subprocess.run(
            ["gcc", "-o", binary,
             os.path.join(tmpdir, "forgery_poc.c"),
             os.path.join(tmpdir, "tweetnacl.c"), "-O2"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"forgery_poc.c compilation failed:\n{result.stderr}"

        result = subprocess.run([binary], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"forgery_poc execution failed:\n{result.stderr}"

        output = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                output[key.strip()] = val.strip()
        _forgery_cache = output
        return output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_forgery_poc_exists():
    """The forgery proof-of-concept source file must exist."""
    assert os.path.isfile("/app/forgery_poc.c"), "/app/forgery_poc.c does not exist"


def test_forgery_poc_compiles_and_runs():
    """The forgery PoC must compile with the fixed tweetnacl and execute successfully."""
    _get_forgery_output()


def test_forgery_poc_divergent():
    """The forgery PoC must demonstrate MAC divergence (DIVERGENT=YES)."""
    output = _get_forgery_output()
    assert output.get("DIVERGENT") == "YES", (
        f"PoC did not demonstrate MAC divergence. Got DIVERGENT={output.get('DIVERGENT', 'MISSING')}"
    )


def test_forgery_poc_key_triggers_bug():
    """The forgery key must have byte 11 bits 4-5 set to trigger the clamping difference."""
    output = _get_forgery_output()
    key_hex = output.get("FORGERY_KEY", "")
    assert len(key_hex) == 64, f"FORGERY_KEY must be 32 bytes (64 hex chars), got {len(key_hex)}"
    key_bytes = bytes.fromhex(key_hex)
    assert (key_bytes[11] & 0x30) != 0, (
        f"Key byte 11 (0x{key_bytes[11]:02x}) has no bits 4-5 set — clamping bug would not trigger"
    )


def test_forgery_poc_mac_format():
    """The PoC must output valid hex MACs that are different from each other."""
    output = _get_forgery_output()
    correct_mac = output.get("CORRECT_MAC", "")
    broken_mac = output.get("BROKEN_MAC", "")
    assert len(correct_mac) == 32, f"CORRECT_MAC must be 16 bytes (32 hex chars), got {len(correct_mac)}"
    assert len(broken_mac) == 32, f"BROKEN_MAC must be 16 bytes (32 hex chars), got {len(broken_mac)}"
    # Validate hex encoding
    bytes.fromhex(correct_mac)
    bytes.fromhex(broken_mac)
    assert correct_mac != broken_mac, "CORRECT_MAC and BROKEN_MAC should differ for a valid vulnerability demo"


def test_forgery_poc_message_present():
    """The PoC must output a non-empty hex-encoded message."""
    output = _get_forgery_output()
    msg_hex = output.get("FORGERY_MSG", "")
    assert len(msg_hex) > 0, "FORGERY_MSG must be non-empty"
    assert len(msg_hex) % 2 == 0, "FORGERY_MSG must be valid hex (even length)"
    bytes.fromhex(msg_hex)


# ============================================================
# Bug report tests
# ============================================================

def test_bug_report_exists():
    """The bug report file must exist."""
    assert os.path.isfile("/app/bug_report.json"), "/app/bug_report.json does not exist"


def test_bug_report_structure():
    """The bug report must be a JSON array of 4 objects with required fields."""
    with open("/app/bug_report.json") as f:
        report = json.load(f)
    assert isinstance(report, list), "bug_report.json must be a JSON array"
    assert len(report) == 4, f"Expected 4 bug entries, got {len(report)}"
    required_fields = {"primitive", "description", "security_impact", "exploitability"}
    valid_impacts = {"authentication_bypass", "encryption_failure", "interop_failure", "key_exchange_failure"}
    valid_exploitability = {"actively_exploitable", "passive_failure"}
    for i, entry in enumerate(report):
        missing = required_fields - set(entry.keys())
        assert not missing, f"Bug entry {i} missing fields: {missing}"
        assert entry["security_impact"] in valid_impacts, (
            f"Bug entry {i}: invalid security_impact '{entry['security_impact']}'"
        )
        assert entry["exploitability"] in valid_exploitability, (
            f"Bug entry {i}: invalid exploitability '{entry['exploitability']}'"
        )


def test_bug_report_primitives():
    """The bug report must correctly identify all affected primitives."""
    with open("/app/bug_report.json") as f:
        report = json.load(f)
    primitives = [entry["primitive"] for entry in report]
    primitive_set = set(primitives)
    assert "poly1305" in primitive_set, "Bug report must include a poly1305 bug"
    assert "curve25519" in primitive_set, "Bug report must include a curve25519 bug"
    assert any("salsa" in p for p in primitive_set), "Bug report must include salsa20 bug(s)"
    salsa_count = sum(1 for p in primitives if "salsa" in p)
    assert salsa_count >= 2, f"Expected at least 2 salsa20 bugs, found {salsa_count}"


def test_bug_report_poly1305_exploitable():
    """The Poly1305 clamping bug must be classified as actively exploitable authentication bypass."""
    with open("/app/bug_report.json") as f:
        report = json.load(f)
    poly_entries = [e for e in report if e["primitive"] == "poly1305"]
    assert len(poly_entries) >= 1, "Must have at least one poly1305 bug entry"
    assert any(e.get("exploitability") == "actively_exploitable" for e in poly_entries), (
        "Poly1305 clamping bug must be classified as 'actively_exploitable'"
    )
    assert any(e.get("security_impact") == "authentication_bypass" for e in poly_entries), (
        "Poly1305 clamping bug must be classified as 'authentication_bypass'"
    )
