"""
test_state.py - Verification tests for libsecops security audit task.

Checks that the agent correctly identified and fixed the security
vulnerabilities in the KEM and KDF subsystems.

"""

import subprocess
import os
import glob


def _run(cmd, **kwargs):
    """Run a command and return the CompletedProcess."""
    defaults = dict(capture_output=True, text=True, timeout=60)
    defaults.update(kwargs)
    return subprocess.run(cmd, **defaults)


def test_project_compiles():
    """The patched project compiles without errors."""
    result = _run(["make", "-C", "/app", "clean", "all"])
    assert result.returncode == 0, (
        f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_basic_tests_pass():
    """Original basic test suite still passes after patching."""
    # Ensure a fresh build first
    _run(["make", "-C", "/app", "clean", "all"])
    result = _run(["make", "-C", "/app", "test"])
    assert result.returncode == 0, (
        f"Basic tests failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_kem_rejects_encrypt_failure():
    """KEM encapsulate must return 0 and cleanse secret when RSA encrypt fails."""
    _run(["make", "-C", "/app", "clean", "all"])

    compile_r = _run([
        "gcc", "-Wall", "-Wextra", "-std=c11",
        "-I/app/include", "-o", "/tmp/test_edge_kem",
        "/tests/test_edge_kem.c", "/app/libsecops.a",
    ])
    assert compile_r.returncode == 0, (
        f"Edge KEM test compile failed: {compile_r.stderr}"
    )

    run_r = _run(["/tmp/test_edge_kem"], timeout=10)
    assert run_r.returncode == 0, (
        f"KEM edge-case test failed (rc={run_r.returncode}):\n{run_r.stdout}"
    )


def test_kdf_parameter_validation():
    """KDF must reject invalid salt type, NULL keylength, and excessive keylength."""
    _run(["make", "-C", "/app", "clean", "all"])

    compile_r = _run([
        "gcc", "-Wall", "-Wextra", "-std=c11",
        "-I/app/include", "-o", "/tmp/test_edge_kdf",
        "/tests/test_edge_kdf.c", "/app/libsecops.a",
    ])
    assert compile_r.returncode == 0, (
        f"Edge KDF test compile failed: {compile_r.stderr}"
    )

    run_r = _run(["/tmp/test_edge_kdf"], timeout=10)
    assert run_r.returncode == 0, (
        f"KDF edge-case test failed (rc={run_r.returncode}):\n{run_r.stdout}"
    )


def test_regression_tests_exist():
    """Agent wrote at least one regression test file beyond test_basic.c."""
    test_files = [
        f for f in glob.glob("/app/tests/test_*.c")
        if os.path.basename(f) != "test_basic.c"
    ]
    assert len(test_files) > 0, (
        "Expected regression tests in /app/tests/ (e.g. test_security.c)"
    )
