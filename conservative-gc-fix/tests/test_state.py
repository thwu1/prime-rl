
"""
Tests for the conservative mark-sweep garbage collector.
Each test compiles a C driver against /app/gc.c and verifies output.
"""

import os
import subprocess
import pytest

COMPILE_CMD = ["gcc", "-std=c11", "-g", "-O1", "-Wall", "-I/app"]
TIMEOUT_COMPILE = 60
TIMEOUT_RUN = 30


def compile_and_run(test_c, timeout_run=TIMEOUT_RUN):
    """Compile a test C file against the GC, run the binary, return result."""
    name = os.path.basename(test_c).replace(".c", "")
    binary = f"/tmp/gc_test_{name}"
    comp = subprocess.run(
        COMPILE_CMD + ["-o", binary, "/app/gc.c", test_c],
        capture_output=True, text=True, timeout=TIMEOUT_COMPILE,
    )
    assert comp.returncode == 0, f"Compilation failed:\n{comp.stderr}"
    result = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout_run
    )
    return result


class TestBasicGC:
    def test_alloc_and_collect(self):
        r = compile_and_run("/tests/test_basic.c")
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS" in r.stdout


class TestInteriorPointers:
    def test_interior_pointer_keeps_object_alive(self):
        r = compile_and_run("/tests/test_interior.c")
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS" in r.stdout


class TestScanRange:
    def test_last_field_scanned(self):
        r = compile_and_run("/tests/test_lastfield.c")
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS" in r.stdout


class TestFinalizers:
    def test_finalizer_features(self):
        r = compile_and_run("/tests/test_finalizers.c")
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS: finalizer_data" in r.stdout, \
            f"finalizer data check failed:\n{r.stdout}"
        assert "PASS: finalizer_order" in r.stdout, \
            f"finalizer ordering check failed:\n{r.stdout}"
        assert "PASS: finalizer_cycle" in r.stdout, \
            f"finalizer cycle detection failed:\n{r.stdout}"


class TestDisappearingLinks:
    def test_dlink_nulled(self):
        r = compile_and_run("/tests/test_dlink.c")
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS" in r.stdout


class TestStress:
    def test_stress(self):
        r = compile_and_run("/tests/test_stress.c", timeout_run=60)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        assert "PASS" in r.stdout
