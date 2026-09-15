
import subprocess
import os
import pytest


def _cmake_configure():
    """Run cmake configure step."""
    return subprocess.run(
        ["cmake", "-B", "/app/build", "-S", "/app"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )


def _cmake_build():
    """Run cmake build step (assumes configure already done)."""
    return subprocess.run(
        ["cmake", "--build", "/app/build"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )


def _full_build():
    """Configure and build. Returns the build result."""
    cfg = _cmake_configure()
    if cfg.returncode != 0:
        return cfg
    return _cmake_build()


def _run_test_incircle():
    """Run the test_incircle binary."""
    return subprocess.run(
        ["/app/build/test_incircle"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )


def _run_verify_mpfr():
    """Run the verify_mpfr binary."""
    return subprocess.run(
        ["/app/build/verify_mpfr"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )


class TestFileExistence:
    """Verify all required deliverables exist."""

    def test_incircle_h_exists(self):
        assert os.path.isfile("/app/incircle.h"), \
            "incircle.h not found at /app/incircle.h"

    def test_verify_mpfr_cpp_exists(self):
        assert os.path.isfile("/app/verify_mpfr.cpp"), \
            "verify_mpfr.cpp not found at /app/verify_mpfr.cpp"

    def test_cmakelists_exists(self):
        assert os.path.isfile("/app/CMakeLists.txt"), \
            "CMakeLists.txt not found at /app/CMakeLists.txt"


class TestIncircleHeader:
    """Verify incircle.h has the required API surface."""

    def test_contains_namespace(self):
        with open("/app/incircle.h") as f:
            content = f.read()
        assert "namespace robust" in content, \
            "incircle.h must define namespace robust"

    def test_contains_incircle_function(self):
        with open("/app/incircle.h") as f:
            content = f.read()
        assert "incircle" in content, \
            "incircle.h must define an incircle function"


class TestBuild:
    """Verify cmake build succeeds and produces both binaries."""

    def test_cmake_configure_succeeds(self):
        result = _cmake_configure()
        assert result.returncode == 0, \
            f"cmake configure failed:\n{result.stderr}"

    def test_cmake_build_succeeds(self):
        result = _full_build()
        assert result.returncode == 0, \
            f"cmake build failed:\n{result.stderr}"

    def test_test_incircle_binary_exists(self):
        _full_build()
        assert os.path.isfile("/app/build/test_incircle"), \
            "test_incircle binary not produced by build"

    def test_verify_mpfr_binary_exists(self):
        _full_build()
        assert os.path.isfile("/app/build/verify_mpfr"), \
            "verify_mpfr binary not produced by build"


class TestCorrectness:
    """Run the C++ test harness and verify all tests pass."""

    def setup_method(self):
        result = _full_build()
        if result.returncode != 0:
            pytest.skip(f"Build failed: {result.stderr}")

    def test_all_cpp_tests_pass(self):
        result = _run_test_incircle()
        assert "ALL_TESTS_PASSED" in result.stdout, (
            f"Not all tests passed.\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_no_failures_reported(self):
        result = _run_test_incircle()
        assert "FAIL " not in result.stdout, \
            f"Test failures detected:\n{result.stdout}"

    def test_exit_code_zero(self):
        result = _run_test_incircle()
        assert result.returncode == 0, (
            f"Test binary exited with code {result.returncode}\n"
            f"{result.stdout}"
        )


class TestMPFRVerification:
    """Run the MPFR verification program and check results."""

    def setup_method(self):
        result = _full_build()
        if result.returncode != 0:
            pytest.skip(f"Build failed: {result.stderr}")

    def test_mpfr_verification_passes(self):
        result = _run_verify_mpfr()
        assert "MPFR_VERIFICATION_PASSED" in result.stdout, (
            f"MPFR verification failed.\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_mpfr_no_mismatches(self):
        result = _run_verify_mpfr()
        assert "MISMATCH" not in result.stdout, \
            f"MPFR mismatches found:\n{result.stdout}"

    def test_mpfr_exit_code_zero(self):
        result = _run_verify_mpfr()
        assert result.returncode == 0, (
            f"verify_mpfr exited with code {result.returncode}\n"
            f"{result.stdout}"
        )


class TestNoExternalLibs:
    """Verify incircle.h does not use external arbitrary-precision libraries."""

    def test_no_gmp_include(self):
        with open("/app/incircle.h") as f:
            content = f.read()
        assert "#include <gmp" not in content, \
            "incircle.h must not include GMP"

    def test_no_mpfr_include(self):
        with open("/app/incircle.h") as f:
            content = f.read()
        assert "#include <mpfr" not in content, \
            "incircle.h must not include MPFR"

    def test_no_boost_multiprecision(self):
        with open("/app/incircle.h") as f:
            content = f.read()
        assert "boost/multiprecision" not in content, \
            "incircle.h must not use Boost.Multiprecision"
