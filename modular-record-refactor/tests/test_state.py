
"""
Tests for the refactored binary record processing library.

Verifies:
  - Build succeeds and produces librecord.a
  - Modular decomposition (>=4 .c files, record_internal.h)
  - No global mutable state (nm symbol check)
  - Header hygiene (no g_rec_errno/g_rec_errmsg in record.h, rec_error_t present)
  - Functional correctness (compile + run C test programs against new API)
  - Thread safety (concurrent parse/format with 4 threads)
  - Binary compatibility (golden reference data from original code)
"""

import pytest
import subprocess
import os

APP_DIR = "/app"
TEST_DIR = "/tests"


def run(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)


# ---- Build fixture (runs once) ----

@pytest.fixture(scope="session", autouse=True)
def build_library():
    """Build the library before any tests run."""
    run(["make", "clean"], cwd=APP_DIR)
    result = run(["make"], cwd=APP_DIR)
    assert result.returncode == 0, (
        f"make failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---- Structural tests ----

class TestBuildOutput:
    def test_library_exists(self):
        path = os.path.join(APP_DIR, "librecord.a")
        assert os.path.isfile(path), "librecord.a not produced by make"

    def test_internal_header_exists(self):
        """At least one internal header besides record.h and api_spec.h."""
        h_files = [
            f for f in os.listdir(APP_DIR)
            if f.endswith(".h") and f not in ("record.h", "api_spec.h")
        ]
        assert len(h_files) >= 1, (
            "No internal header found besides record.h. "
            "Decomposed library should have a shared internal header."
        )

    def test_at_least_four_source_files(self):
        c_files = [
            f for f in os.listdir(APP_DIR)
            if f.endswith(".c") and f != "main.c"
        ]
        assert len(c_files) >= 4, (
            f"Need >=4 .c files (excluding main.c), found {len(c_files)}: {c_files}"
        )


class TestNoGlobalMutableState:
    def _nm_output(self):
        result = run(["nm", os.path.join(APP_DIR, "librecord.a")])
        return result.stdout

    def test_no_g_rec_errno(self):
        assert "g_rec_errno" not in self._nm_output(), \
            "Global variable g_rec_errno still exported from library"

    def test_no_g_rec_errmsg(self):
        assert "g_rec_errmsg" not in self._nm_output(), \
            "Global variable g_rec_errmsg still exported from library"

    def test_no_fmt_buf(self):
        assert "fmt_buf" not in self._nm_output(), \
            "Static format buffer fmt_buf still in library"

    def test_no_crc_table_ready(self):
        out = self._nm_output()
        assert "crc_table_ready" not in out, \
            "Mutable crc_table_ready still in library"
        assert "crc_table_init" not in out, \
            "Mutable crc_table_init still in library"


class TestHeaderHygiene:
    def _header_content(self):
        with open(os.path.join(APP_DIR, "record.h")) as f:
            return f.read()

    def test_no_global_errno_in_header(self):
        content = self._header_content()
        assert "g_rec_errno" not in content, \
            "g_rec_errno declaration still in public header"

    def test_no_global_errmsg_in_header(self):
        content = self._header_content()
        assert "g_rec_errmsg" not in content, \
            "g_rec_errmsg declaration still in public header"

    def test_error_type_defined(self):
        content = self._header_content()
        assert "rec_error_t" in content, \
            "rec_error_t not defined in public header"

    def test_no_rec_strerror_in_header(self):
        content = self._header_content()
        assert "rec_strerror" not in content, \
            "Legacy rec_strerror accessor still in public header"

    def test_no_rec_errno_func_in_header(self):
        """rec_errno() accessor for global state should be removed."""
        content = self._header_content()
        # Must not have 'rec_errno' as a function declaration.
        # But 'g_rec_errno' is already checked above; be precise:
        # Look for 'rec_errno' NOT preceded by 'g_'
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue
            if "rec_errno" in stripped and "g_rec_errno" not in stripped \
               and "REC_ERR" not in stripped and "rec_error" not in stripped:
                pytest.fail(
                    f"Legacy rec_errno function still in header: {stripped}"
                )


# ---- Functional tests (compile and run C test programs) ----

class TestFunctional:
    def test_compile_and_run_functional_tests(self):
        src = os.path.join(TEST_DIR, "test_functional.c")
        exe = "/tmp/test_functional"
        result = run([
            "gcc", "-I" + APP_DIR, "-o", exe, src,
            "-L" + APP_DIR, "-lrecord",
        ])
        assert result.returncode == 0, (
            f"Compilation failed (API signature mismatch?):\n{result.stderr}"
        )

        result = run([exe], timeout=30)
        assert result.returncode == 0, (
            f"Functional tests failed:\n{result.stdout}\n{result.stderr}"
        )


class TestThreadSafety:
    def test_compile_and_run_thread_tests(self):
        src = os.path.join(TEST_DIR, "test_threads.c")
        exe = "/tmp/test_threads"
        result = run([
            "gcc", "-I" + APP_DIR, "-o", exe, src,
            "-L" + APP_DIR, "-lrecord", "-lpthread",
        ])
        assert result.returncode == 0, (
            f"Thread test compilation failed:\n{result.stderr}"
        )

        result = run([exe], timeout=60)
        assert result.returncode == 0, (
            f"Thread safety test failed:\n{result.stdout}\n{result.stderr}"
        )


class TestGoldenCompatibility:
    def test_golden_files_exist(self):
        golden_dir = os.path.join(APP_DIR, "golden")
        assert os.path.isdir(golden_dir), \
            "Golden reference directory /app/golden/ not found"
        expected = ["metric.bin", "log.bin", "alert.bin", "trace.bin", "audit.bin"]
        for fname in expected:
            path = os.path.join(golden_dir, fname)
            assert os.path.isfile(path), f"Golden file {fname} missing"

    def test_compile_and_run_golden_tests(self):
        src = os.path.join(TEST_DIR, "test_golden.c")
        exe = "/tmp/test_golden"
        result = run([
            "gcc", "-I" + APP_DIR, "-o", exe, src,
            "-L" + APP_DIR, "-lrecord", "-lm",
        ])
        assert result.returncode == 0, (
            f"Golden test compilation failed:\n{result.stderr}"
        )

        result = run([exe], timeout=30)
        assert result.returncode == 0, (
            f"Golden compatibility tests failed:\n{result.stdout}\n{result.stderr}"
        )
