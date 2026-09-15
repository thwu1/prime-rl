
"""
Pytest tests verifying correctness of the Triint64 OCaml module.
Builds the project, runs the differential test driver, and checks
specific operation categories for correctness.
"""

import subprocess
import os
import pytest

_cached = {}

def _build_and_run():
    """Build and run the test driver once, cache the result."""
    if "result" in _cached:
        return _cached["result"]

    build = subprocess.run(
        ["dune", "build"], cwd="/app",
        capture_output=True, text=True, timeout=120
    )
    if build.returncode != 0:
        _cached["result"] = {
            "build_ok": False, "build_stderr": build.stderr,
            "stdout": "", "stderr": "", "rc": -1, "timed_out": False
        }
        return _cached["result"]

    try:
        run = subprocess.run(
            ["dune", "exec", "./main.exe"], cwd="/app",
            capture_output=True, text=True, timeout=120
        )
        _cached["result"] = {
            "build_ok": True, "build_stderr": "",
            "stdout": run.stdout, "stderr": run.stderr,
            "rc": run.returncode, "timed_out": False
        }
    except subprocess.TimeoutExpired:
        _cached["result"] = {
            "build_ok": True, "build_stderr": "",
            "stdout": "", "stderr": "", "rc": -1, "timed_out": True
        }
    return _cached["result"]


class TestBuild:
    def test_dune_build_succeeds(self):
        r = _build_and_run()
        assert r["build_ok"], f"Build failed: {r['build_stderr']}"

    def test_executable_exists(self):
        r = _build_and_run()
        assert r["build_ok"]
        assert os.path.exists("/app/_build/default/main.exe") or \
               os.path.exists("/app/_build/default/./main.exe")


class TestDriver:
    def test_no_timeout(self):
        r = _build_and_run()
        assert not r["timed_out"], \
            "Test driver timed out (possible infinite loop in to_string or similar)"

    def test_all_tests_pass(self):
        r = _build_and_run()
        assert r["build_ok"]
        assert not r["timed_out"], "Driver timed out"
        assert r["rc"] == 0, f"Exit code {r['rc']}. stderr: {r['stderr'][:1000]}"
        assert "ALL TESTS PASSED" in r["stdout"], \
            f"Expected ALL TESTS PASSED. stdout: {r['stdout'][:500]}"


class TestMul:
    def test_no_mul_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL mul(" not in r["stderr"], \
            "mul() has carry propagation errors"
        assert "FAIL mul_rand(" not in r["stderr"], \
            "mul() fails on random inputs"


class TestCompare:
    def test_no_compare_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL compare(" not in r["stderr"], \
            "compare() sign-extension bug"
        assert "FAIL compare_rand(" not in r["stderr"]


class TestShiftRight:
    def test_no_shift_right_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL shr(" not in r["stderr"], \
            "shift_right has sign-extension bug in 24-47 range"
        assert "FAIL shr_rand(" not in r["stderr"]


class TestDiv:
    def test_no_div_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL div(" not in r["stderr"], \
            "div() min_int edge case bug"
        assert "FAIL div_rand(" not in r["stderr"]

    def test_no_mod_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL mod(" not in r["stderr"], \
            "modulo() min_int edge case bug"
        assert "FAIL mod_rand(" not in r["stderr"]


class TestToString:
    def test_no_to_string_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL to_string(" not in r["stderr"], \
            "to_string() likely has min_int infinite loop"


class TestHash:
    def test_no_hash_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL hash(" not in r["stderr"], \
            "hash() doesn't match Hashtbl.hash"
        assert "FAIL hash_rand(" not in r["stderr"]


class TestMarshal:
    def test_no_marshal_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL marshal_len(" not in r["stderr"], \
            "marshal() produces wrong length"
        assert "FAIL marshal_content(" not in r["stderr"], \
            "marshal() produces wrong bytes"
        assert "FAIL unmarshal(" not in r["stderr"], \
            "unmarshal() round-trip failure"
        assert "FAIL marshal_roundtrip(" not in r["stderr"]


class TestPopcount:
    def test_no_popcount_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL popcount(" not in r["stderr"], \
            "popcount() misses bits in some limb(s)"
        assert "FAIL popcount_rand(" not in r["stderr"]


class TestClz:
    def test_no_clz_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL clz(" not in r["stderr"], \
            "clz() has offset error between limbs"
        assert "FAIL clz_rand(" not in r["stderr"]


class TestRotateLeft:
    def test_no_rotate_left_failures(self):
        r = _build_and_run()
        assert r["build_ok"] and not r["timed_out"]
        assert "FAIL rotl(" not in r["stderr"], \
            "rotate_left() complement shift count error"
        assert "FAIL rotl_rand(" not in r["stderr"]
