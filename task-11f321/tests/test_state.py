"""
test_state.py -- Compile and run the C test suites against the
agent's gc.c implementation, and verify build system / memory safety.

"""

import os
import subprocess
import pytest
import xml.etree.ElementTree as ET


def _compile(test_name: str) -> str:
    """Compile /tests/<test_name>.c with /app/gc.c -> /tmp/<test_name>."""
    binary = f"/tmp/{test_name}"
    result = subprocess.run(
        [
            "gcc", "-o", binary,
            f"/tests/{test_name}.c", "/app/gc.c",
            "-I/app", "-Wall", "-std=c11", "-O1", "-g",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Compilation of {test_name} failed:\n{result.stderr}"
    )
    return binary


def _run(binary: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a compiled test binary."""
    return subprocess.run(
        [binary],
        capture_output=True, text=True, timeout=timeout,
    )


# ------------------------------------------------------------------
# Functional Tests
# ------------------------------------------------------------------

class TestGCFileExists:
    def test_gc_c_exists(self):
        assert os.path.exists("/app/gc.c"), (
            "/app/gc.c not found -- the agent must create this file"
        )

    def test_gc_h_exists(self):
        assert os.path.exists("/app/gc.h"), (
            "/app/gc.h not found -- it should have been placed by the Dockerfile"
        )


class TestBasicGC:
    def test_compiles(self):
        _compile("test_basic")

    def test_passes(self):
        binary = _compile("test_basic")
        result = _run(binary)
        assert result.returncode == 0, (
            f"test_basic exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ALL TESTS PASSED" in result.stdout, (
            f"test_basic did not report ALL TESTS PASSED\n"
            f"stdout:\n{result.stdout}"
        )


class TestEphemerons:
    def test_compiles(self):
        _compile("test_ephemerons")

    def test_passes(self):
        binary = _compile("test_ephemerons")
        result = _run(binary)
        assert result.returncode == 0, (
            f"test_ephemerons exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ALL TESTS PASSED" in result.stdout, (
            f"test_ephemerons did not report ALL TESTS PASSED\n"
            f"stdout:\n{result.stdout}"
        )


class TestStress:
    def test_compiles(self):
        _compile("test_stress")

    def test_passes(self):
        binary = _compile("test_stress")
        result = _run(binary, timeout=180)
        assert result.returncode == 0, (
            f"test_stress exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ALL TESTS PASSED" in result.stdout, (
            f"test_stress did not report ALL TESTS PASSED\n"
            f"stdout:\n{result.stdout}"
        )


# ------------------------------------------------------------------
# Build System Tests
# ------------------------------------------------------------------

class TestBuildSystem:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), (
            "/app/Makefile not found -- the agent must create this file"
        )

    def test_make_all_produces_library(self):
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"make all failed:\n{result.stderr}"
        )
        assert os.path.exists("/app/libgc.a"), (
            "libgc.a not produced by make all"
        )

    def test_make_clean_removes_artifacts(self):
        # Build first
        subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, timeout=60,
        )
        # Clean
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"make clean failed:\n{result.stderr}"
        )
        assert not os.path.exists("/app/libgc.a"), (
            "libgc.a still present after make clean"
        )


# ------------------------------------------------------------------
# Memory Safety Tests
# ------------------------------------------------------------------

class TestAddressSanitizer:
    def test_asan_clean(self):
        """Build and run test_basic with AddressSanitizer via Makefile."""
        # Disable LeakSanitizer — it does not work reliably in
        # containerised environments (ptrace restrictions).  Leak
        # detection is covered separately by the Valgrind tests.
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        result = subprocess.run(
            ["make", "-C", "/app", "asan"],
            capture_output=True, text=True, timeout=120,
            env=env,
        )
        assert result.returncode == 0, (
            f"ASan test failed (exit {result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


class TestValgrind:
    def _ensure_valgrind_run(self):
        """Run make valgrind to produce the XML report."""
        # Clean any stale report first
        report = "/app/valgrind-report.xml"
        if os.path.exists(report):
            os.remove(report)
        result = subprocess.run(
            ["make", "-C", "/app", "valgrind"],
            capture_output=True, text=True, timeout=180,
        )
        return result

    def test_valgrind_report_exists(self):
        self._ensure_valgrind_run()
        assert os.path.exists("/app/valgrind-report.xml"), (
            "Valgrind XML report not produced at /app/valgrind-report.xml"
        )

    def test_valgrind_report_parseable(self):
        self._ensure_valgrind_run()
        assert os.path.exists("/app/valgrind-report.xml"), (
            "Valgrind XML report missing"
        )
        tree = ET.parse("/app/valgrind-report.xml")
        root = tree.getroot()
        assert root is not None, "XML report has no root element"

    def test_valgrind_zero_errors(self):
        self._ensure_valgrind_run()
        assert os.path.exists("/app/valgrind-report.xml"), (
            "Valgrind XML report missing"
        )
        tree = ET.parse("/app/valgrind-report.xml")
        root = tree.getroot()
        errors = root.findall(".//error")
        if errors:
            details = []
            for e in errors:
                kind_el = e.find("kind")
                what_el = e.find("what") or e.find("xwhat/text")
                kind = kind_el.text if kind_el is not None else "unknown"
                what = what_el.text if what_el is not None else "no details"
                details.append(f"  {kind}: {what}")
            assert False, (
                f"Valgrind found {len(errors)} error(s):\n"
                + "\n".join(details)
            )
