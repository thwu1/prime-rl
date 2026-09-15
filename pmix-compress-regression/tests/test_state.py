"""
Verification tests for the PMIx PPN multi-backend compression task.

"""
import subprocess
import os
import re
import pytest


def _build():
    """Build the project from clean state, return (success, stderr)."""
    subprocess.run(["make", "clean"], cwd="/app", capture_output=True)
    r = subprocess.run(
        ["make"], cwd="/app", capture_output=True, text=True, timeout=120
    )
    return r.returncode == 0, r.stderr


def _run_tests():
    """Run the test_ppn binary, return (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["/app/test_ppn"],
        capture_output=True, text=True, timeout=120
    )
    return r.returncode, r.stdout, r.stderr


class TestBuild:
    def test_compiles_cleanly(self):
        """Source code compiles without errors after fix."""
        ok, err = _build()
        assert ok, f"Compilation failed:\n{err}"

    def test_binary_produced(self):
        """Build produces the test_ppn binary."""
        _build()
        assert os.path.isfile("/app/test_ppn"), "test_ppn binary not found"


class TestRoundtrip:
    @pytest.fixture(autouse=True)
    def _build_project(self):
        ok, err = _build()
        assert ok, f"Build failed:\n{err}"

    def test_all_cases_pass(self):
        """All 12 test cases pass (backend + roundtrip + compat)."""
        rc, stdout, stderr = _run_tests()
        assert rc == 0, f"test_ppn exited {rc}:\n{stdout}\n{stderr}"
        m = re.search(r"(\d+)/(\d+) tests passed", stdout)
        assert m, f"Could not find result line in output:\n{stdout}"
        passed, total = int(m.group(1)), int(m.group(2))
        assert passed == 12 and total == 12, (
            f"Expected 12/12 tests passed, got {passed}/{total}:\n{stdout}"
        )

    def test_boundary_over_passes(self):
        """The 1042-procs/9-nodes boundary case passes."""
        _, stdout, _ = _run_tests()
        assert "1042 procs" in stdout, "1042-proc test case not found"
        lines = stdout.split("\n")
        found_case = False
        for line in lines:
            if "1042 procs" in line:
                found_case = True
            elif found_case and "PASS" in line:
                return
            elif found_case and "FAIL" in line:
                pytest.fail(
                    f"1042-proc boundary case failed:\n{stdout}"
                )
        assert found_case, "1042-proc test case not found"
        pytest.fail("1042-proc case produced no PASS/FAIL verdict")

    def test_large_proc_counts_pass(self):
        """Large process counts (20000, 50000) all pass."""
        _, stdout, _ = _run_tests()
        for nprocs in [20000, 50000]:
            assert f"{nprocs} procs" in stdout, (
                f"{nprocs}-proc test case not found"
            )
            lines = stdout.split("\n")
            found = False
            for line in lines:
                if f"{nprocs} procs" in line:
                    found = True
                elif found and "PASS" in line:
                    break
                elif found and "FAIL" in line:
                    pytest.fail(f"{nprocs}-proc test failed:\n{stdout}")
            assert found, f"{nprocs}-proc test case not found"

    def test_blob2_format_used(self):
        """blob2 format IS used for large maps (v2 encoder must work)."""
        _, stdout, _ = _run_tests()
        assert "format=blob2:" in stdout, (
            "No blob2: format encoding found in output. The v2 compressed "
            "backend should be used for large maps."
        )

    def test_lz4_backend_works(self):
        """LZ4 backend compress/decompress roundtrip passes."""
        _, stdout, _ = _run_tests()
        assert "lz4-backend" in stdout, (
            "LZ4 backend test not found in output"
        )
        lines = stdout.split("\n")
        found = False
        for line in lines:
            if "lz4-backend" in line:
                found = True
            elif found and "PASS" in line:
                return
            elif found and "FAIL" in line:
                pytest.fail(f"LZ4 backend test failed:\n{stdout}")
        assert found, "LZ4 backend test not found"
        pytest.fail("LZ4 backend test produced no PASS/FAIL verdict")

    def test_v1_backward_compat(self):
        """v1 blob format can still be parsed by the general parser."""
        _, stdout, _ = _run_tests()
        assert "v1-compat" in stdout, (
            "V1 backward compatibility test not found in output"
        )
        lines = stdout.split("\n")
        found = False
        for line in lines:
            if "v1-compat" in line:
                found = True
            elif found and "PASS" in line:
                return
            elif found and "FAIL" in line:
                pytest.fail(
                    f"V1 backward compat test failed:\n{stdout}"
                )
        assert found, "V1 compat test not found"
        pytest.fail("V1 compat test produced no PASS/FAIL verdict")

    def test_v2_reports_algorithm(self):
        """v2 encoder reports which compression algorithm was selected."""
        _, stdout, _ = _run_tests()
        algo_matches = re.findall(r"algo=(zlib|lz4)", stdout)
        assert len(algo_matches) > 0, (
            "No algorithm ID found in v2 blob output. The v2 encoder should "
            "report which compression algorithm (zlib or lz4) was selected."
        )
