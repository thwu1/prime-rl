#!/usr/bin/env python3
"""
Verification tests for the NDP dissector vulnerability triage task.

Checks:
  1. vulns.json has correct structure, CWE classifications, and challenge_token
  2. PoV inputs crash the original (unpatched) binary
  3. Patched source prevents PoV crashes
  4. Valid test inputs still work after patching
"""


import json
import os
import re
import subprocess
import pytest

APP_DIR = '/app'
ORIG_SRC = os.path.join(APP_DIR, '.orig_src')
PATCHED_SRC = os.path.join(APP_DIR, 'src')
POV_DIR = os.path.join(APP_DIR, 'pov')
TESTDATA_DIR = os.path.join(APP_DIR, 'testdata')
VULNS_FILE = os.path.join(APP_DIR, 'vulns.json')

SRC_FILES = ['main.c', 'probe.c', 'ident.c', 'auth.c', 'bulk.c', 'diag.c', 'util.c']

# Build WITHOUT -fsanitize=address.  ASAN adds red-zone padding around stack
# buffers at compile time; if the ASAN runtime cannot map shadow memory in a
# restricted container the red zones absorb the overflow silently and no crash
# is detected.  Building with plain -O1 gives us:
#   - stack-protector (Ubuntu default): catches stack overflows via canary
#   - FORTIFY_SOURCE at -O1: intercepts %n in writable format strings
#   - unmapped-page faults: large heap offsets hit pages beyond the brk
BUILD_FLAGS = '-O1 -Wall -g'


def load_expected_token():
    """Read the expected challenge token from the preserved original source."""
    ndp_h = os.path.join(ORIG_SRC, 'ndp.h')
    with open(ndp_h) as f:
        content = f.read()
    match = re.search(r'#define\s+CHALLENGE_TOKEN\s+"([0-9a-f]+)"', content)
    assert match, "CHALLENGE_TOKEN not found in original ndp.h"
    return match.group(1)


def load_vulns():
    """Load and parse vulns.json, handling both object and array formats."""
    with open(VULNS_FILE) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    # Legacy array format - wrap it
    return {"challenge_token": "", "vulnerabilities": data}


def build_binary(src_dir, output_path):
    """Build a binary from the given source directory."""
    srcs = ' '.join(os.path.join(src_dir, f) for f in SRC_FILES)
    cmd = 'gcc %s -o %s %s' % (BUILD_FLAGS, output_path, srcs)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert result.returncode == 0, \
        "Build from %s failed:\n%s" % (src_dir, result.stderr)
    return output_path


def is_security_crash(result):
    """Determine whether a subprocess result indicates a security-relevant crash.

    Returns True for signal deaths (SIGSEGV, SIGABRT, SIGBUS), stack-smashing
    detection, FORTIFY_SOURCE aborts, and AddressSanitizer errors.  Returns
    False for normal application-level errors (e.g., packet rejected).
    """
    stderr = (result.stderr if isinstance(result.stderr, str)
              else result.stderr.decode('utf-8', errors='replace'))

    # Killed by signal (SIGSEGV=-11, SIGABRT=-6, SIGBUS=-7, etc.)
    if result.returncode < 0:
        return True
    # SIGABRT via exit code 134 (128+6)
    if result.returncode == 134:
        return True
    # SIGBUS via exit code 135 (128+7), SIGSEGV via exit code 139 (128+11)
    if result.returncode in (135, 139):
        return True
    # Stack-smashing protection
    if 'stack smashing detected' in stderr:
        return True
    # FORTIFY_SOURCE %n interception
    if '%n in writable segment detected' in stderr:
        return True
    # fortify_fail generic
    if 'fortify_fail' in stderr.lower():
        return True
    # ASAN detected an error (if binary was built with ASAN)
    if 'AddressSanitizer' in stderr:
        return True
    # Generic sanitizer summary
    if 'SUMMARY' in stderr and 'Sanitizer' in stderr:
        return True

    return False


# ---------------------------------------------------------------------------
# Vulnerability report tests
# ---------------------------------------------------------------------------

class TestVulnReport:
    def test_vulns_file_exists(self):
        assert os.path.exists(VULNS_FILE), \
            "%s not found" % VULNS_FILE

    def test_vulns_is_valid_json(self):
        with open(VULNS_FILE) as f:
            data = json.load(f)
        assert isinstance(data, (dict, list)), \
            "vulns.json must be a JSON object or array"

    def test_challenge_token_correct(self):
        expected = load_expected_token()
        report = load_vulns()
        actual = report.get('challenge_token', '')
        assert actual == expected, \
            "Challenge token mismatch: expected '%s', got '%s'" % (
                expected, actual)

    def test_vulns_has_three_entries(self):
        report = load_vulns()
        vulns = report.get('vulnerabilities', [])
        assert len(vulns) >= 3, \
            "Expected >= 3 vulnerabilities, found %d" % len(vulns)

    def test_vulns_identify_ident(self):
        report = load_vulns()
        vulns = report.get('vulnerabilities', [])
        matches = [v for v in vulns if 'ident' in v.get('file', '').lower()]
        assert len(matches) >= 1, "No vulnerability references ident.c"
        cwe = matches[0].get('cwe', '')
        valid = ['CWE-121', 'CWE-787', 'CWE-120', 'CWE-119', 'CWE-131']
        assert any(c in cwe for c in valid), \
            "ident.c CWE should indicate buffer overflow, got %s" % cwe

    def test_vulns_identify_auth(self):
        report = load_vulns()
        vulns = report.get('vulnerabilities', [])
        matches = [v for v in vulns if 'auth' in v.get('file', '').lower()]
        assert len(matches) >= 1, "No vulnerability references auth.c"
        cwe = matches[0].get('cwe', '')
        assert 'CWE-134' in cwe, \
            "auth.c CWE should be CWE-134 (format string), got %s" % cwe

    def test_vulns_identify_bulk(self):
        report = load_vulns()
        vulns = report.get('vulnerabilities', [])
        matches = [v for v in vulns if 'bulk' in v.get('file', '').lower()]
        assert len(matches) >= 1, "No vulnerability references bulk.c"
        cwe = matches[0].get('cwe', '')
        valid = ['CWE-122', 'CWE-787', 'CWE-119', 'CWE-120']
        assert any(c in cwe for c in valid), \
            "bulk.c CWE should indicate heap overflow, got %s" % cwe


# ---------------------------------------------------------------------------
# PoV crash-on-original tests
# ---------------------------------------------------------------------------

class TestPoVsCrashOriginal:
    @pytest.fixture(scope='class')
    def orig_binary(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp('orig')
        return build_binary(ORIG_SRC, str(tmp / 'ndp_orig'))

    def _run_pov(self, binary, pov_name):
        pov_path = os.path.join(POV_DIR, pov_name)
        assert os.path.exists(pov_path), \
            "%s not found in %s" % (pov_name, POV_DIR)
        try:
            result = subprocess.run(
                [binary, pov_path],
                capture_output=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return True  # treat timeout as crash
        return is_security_crash(result)

    def test_pov1_crashes_original(self, orig_binary):
        assert self._run_pov(orig_binary, 'pov1.bin'), \
            "pov1.bin must trigger a security crash on the original binary"

    def test_pov2_crashes_original(self, orig_binary):
        assert self._run_pov(orig_binary, 'pov2.bin'), \
            "pov2.bin must trigger a security crash on the original binary"

    def test_pov3_crashes_original(self, orig_binary):
        assert self._run_pov(orig_binary, 'pov3.bin'), \
            "pov3.bin must trigger a security crash on the original binary"


# ---------------------------------------------------------------------------
# Patched-binary safety tests
# ---------------------------------------------------------------------------

class TestPatchedSafety:
    @pytest.fixture(scope='class')
    def patched_binary(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp('patched')
        return build_binary(PATCHED_SRC, str(tmp / 'ndp_patched'))

    def _run_pov_safe(self, binary, pov_name):
        pov_path = os.path.join(POV_DIR, pov_name)
        assert os.path.exists(pov_path), "%s not found" % pov_name
        try:
            result = subprocess.run(
                [binary, pov_path],
                capture_output=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False
        return not is_security_crash(result)

    def test_pov1_safe_after_patch(self, patched_binary):
        assert self._run_pov_safe(patched_binary, 'pov1.bin'), \
            "pov1.bin must NOT trigger a security crash after patching"

    def test_pov2_safe_after_patch(self, patched_binary):
        assert self._run_pov_safe(patched_binary, 'pov2.bin'), \
            "pov2.bin must NOT trigger a security crash after patching"

    def test_pov3_safe_after_patch(self, patched_binary):
        assert self._run_pov_safe(patched_binary, 'pov3.bin'), \
            "pov3.bin must NOT trigger a security crash after patching"


# ---------------------------------------------------------------------------
# Functional tests (valid inputs must still work)
# ---------------------------------------------------------------------------

class TestFunctional:
    @pytest.fixture(scope='class')
    def patched_binary(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp('func')
        return build_binary(PATCHED_SRC, str(tmp / 'ndp_func'))

    def test_valid_inputs_work(self, patched_binary):
        """Every valid test packet must be processed without errors."""
        assert os.path.isdir(TESTDATA_DIR), "%s not found" % TESTDATA_DIR
        test_files = sorted(f for f in os.listdir(TESTDATA_DIR)
                            if f.endswith('.bin'))
        assert len(test_files) > 0, "No .bin test files found"

        for tf in test_files:
            path = os.path.join(TESTDATA_DIR, tf)
            result = subprocess.run(
                [patched_binary, path],
                capture_output=True, timeout=10,
            )
            assert not is_security_crash(result), \
                "Valid input %s triggered a security crash" % tf
            assert result.returncode == 0, \
                "Valid input %s returned exit code %d" % (tf, result.returncode)
