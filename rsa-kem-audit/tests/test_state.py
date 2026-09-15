"""
Verification tests for the RSA-KEM security audit task.

Checks that the agent correctly identified and fixed all security
vulnerabilities in the RSASVE implementation.

"""

import subprocess
import re
import os

import pytest


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def get_function_body(content, func_name):
    """Extract the body of a C function (between the opening { and closing })."""
    pattern = rf"int\s+{func_name}\s*\([^)]*\)\s*\{{(.*?)\n\}}"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

class TestCompilation:
    def test_make_clean_build(self):
        """The fixed code must compile without errors."""
        subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
        result = subprocess.run(
            ["make", "-C", "/app", "all"], capture_output=True, text=True
        )
        assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"


# ---------------------------------------------------------------------------
# Return-value handling in rsasve_generate
# ---------------------------------------------------------------------------

class TestReturnValueHandling:
    """RSA_public_encrypt() returns byte-count (>0) on success, -1 on failure.

    The original code used ``if (ret)`` which treats -1 as truthy — a
    critical security bug.
    """

    def _body(self):
        content = read_file("/app/rsa_kem.c")
        body = get_function_body(content, "rsasve_generate")
        assert body is not None, "rsasve_generate not found in rsa_kem.c"
        return body, content

    def test_buggy_pattern_removed(self):
        body, content = self._body()
        if "RSA_public_encrypt" not in body:
            return  # agent replaced with different API
        idx = body.index("RSA_public_encrypt")
        after = body[idx:]
        assert not re.search(r"\bif\s*\(\s*ret\s*\)", after), (
            "Buggy pattern 'if (ret)' still present after RSA_public_encrypt"
        )

    def test_proper_error_check(self):
        body, _ = self._body()
        if "RSA_public_encrypt" not in body:
            return
        idx = body.index("RSA_public_encrypt")
        after = body[idx:]
        has_check = bool(
            re.search(r"ret\s*<=\s*0", after)
            or re.search(r"ret\s*<\s*[01]", after)
            or re.search(r"ret\s*>\s*0", after)
            or re.search(r"ret\s*>=\s*1", after)
            or re.search(r"ret\s*!=\s*.*\bnlen\b", after)
            or re.search(r"ret\s*==\s*.*\bnlen\b", after)
            or re.search(r"\bnlen\b.*!=\s*ret", after)
            or re.search(r"\bnlen\b.*==\s*ret", after)
            or re.search(r"ret\s*==\s*-1", after)
        )
        assert has_check, (
            "No proper return-value check found after RSA_public_encrypt"
        )

    def test_output_length_validated(self):
        body, _ = self._body()
        if "RSA_public_encrypt" not in body:
            return
        idx = body.index("RSA_public_encrypt")
        after = body[idx:]
        has_len = bool(
            re.search(r"ret\s*!=\s*\(?\s*int\s*\)?\s*nlen", after)
            or re.search(r"\(?\s*int\s*\)?\s*nlen\s*!=\s*ret", after)
            or re.search(r"ret\s*==\s*\(?\s*int\s*\)?\s*nlen", after)
            or re.search(r"\(?\s*int\s*\)?\s*nlen\s*==\s*ret", after)
        )
        assert has_len, (
            "Return value not validated against expected output length (nlen)"
        )


# ---------------------------------------------------------------------------
# Secret cleansing
# ---------------------------------------------------------------------------

class TestSecretCleansing:
    def test_cleanse_on_error_path(self):
        """OPENSSL_cleanse must be reachable when RSA_public_encrypt fails."""
        content = read_file("/app/rsa_kem.c")
        body = get_function_body(content, "rsasve_generate")
        assert body is not None
        assert "OPENSSL_cleanse" in body, (
            "OPENSSL_cleanse not found in rsasve_generate"
        )
        pos = body.index("OPENSSL_cleanse")
        after = body[pos:]
        assert "return 0" in after or "return ret" in after, (
            "OPENSSL_cleanse must precede the error return"
        )


# ---------------------------------------------------------------------------
# Input validation in rsasve_recover
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_recover_validates_input_length(self):
        """rsasve_recover must reject ciphertext whose length != nlen."""
        content = read_file("/app/rsa_kem.c")
        body = get_function_body(content, "rsasve_recover")
        assert body is not None, "rsasve_recover not found"
        has_check = bool(
            re.search(r"inlen\s*!=\s*nlen", body)
            or re.search(r"nlen\s*!=\s*inlen", body)
            or re.search(r"inlen\s*<\s*nlen", body)
            or re.search(r"inlen\s*!=.*RSA_size", body)
        )
        assert has_check, (
            "rsasve_recover must validate that inlen matches expected size"
        )


# ---------------------------------------------------------------------------
# Functional correctness
# ---------------------------------------------------------------------------

class TestFunctionalCorrectness:
    def test_roundtrip(self):
        """Encapsulate then decapsulate must recover the same secret."""
        subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
        r = subprocess.run(
            ["make", "-C", "/app", "all"], capture_output=True, text=True
        )
        assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"
        r = subprocess.run(
            ["/app/test_roundtrip"], capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, (
            f"Roundtrip test failed:\n{r.stdout}\n{r.stderr}"
        )
        assert "PASS" in r.stdout, f"Expected PASS in output:\n{r.stdout}"


# ---------------------------------------------------------------------------
# Runtime mock: RSA_public_encrypt returning -1
# ---------------------------------------------------------------------------

class TestErrorHandlingRuntime:
    def test_mock_rsa_failure(self):
        """With RSA_public_encrypt mocked to return -1, rsasve_generate
        must return 0 (failure)."""
        content = read_file("/app/rsa_kem.c")
        if "RSA_public_encrypt" not in content:
            pytest.skip("RSA_public_encrypt not used")

        compile_r = subprocess.run(
            [
                "gcc",
                "-o", "/tmp/test_error_handling",
                "-I/app",
                "-DOPENSSL_SUPPRESS_DEPRECATED",
                "/tests/test_error_handling.c",
                "/app/rsa_kem.c",
                "-Wl,--wrap=RSA_public_encrypt",
                "-lcrypto",
            ],
            capture_output=True,
            text=True,
        )
        if compile_r.returncode != 0:
            pytest.skip(
                f"Mock-test compilation failed (code may have been "
                f"restructured):\n{compile_r.stderr}"
            )

        r = subprocess.run(
            ["/tmp/test_error_handling"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0, (
            f"Error-handling test failed:\n{r.stdout}\n{r.stderr}"
        )
        assert "PASS" in r.stdout, f"Expected PASS:\n{r.stdout}"


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------

class TestAuditReport:
    def test_audit_report_exists(self):
        assert os.path.isfile("/app/AUDIT.md"), (
            "No audit report found at /app/AUDIT.md"
        )

    def test_audit_report_has_content(self):
        content = read_file("/app/AUDIT.md")
        assert len(content) >= 200, "Audit report is too short"
        lo = content.lower()
        has_discussion = (
            "return value" in lo
            or "error handling" in lo
            or "rsa_public_encrypt" in lo
            or "-1" in content
            or "failure" in lo
        )
        assert has_discussion, (
            "Audit report should discuss the return-value handling vulnerability"
        )
