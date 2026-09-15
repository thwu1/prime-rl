
import subprocess
import os
import tempfile
import shutil
import re
import pytest


def run_nvc(*args, timeout=120):
    """Run NVC in a fresh temporary directory with absolute-path source files."""
    tmpdir = tempfile.mkdtemp()
    result = subprocess.run(
        ["nvc"] + list(args),
        capture_output=True, text=True, cwd=tmpdir, timeout=timeout,
    )
    return result, tmpdir


# ---------------------------------------------------------------------------
# Compilation tests
# ---------------------------------------------------------------------------

class TestCompilation:
    def test_alu_compiles(self):
        r, d = run_nvc("-a", "/app/alu.vhd")
        shutil.rmtree(d)
        assert r.returncode == 0, f"ALU compilation failed:\n{r.stderr}"

    def test_testbench_compiles(self):
        r, d = run_nvc("-a", "/app/alu.vhd", "/app/tb_alu.vhd")
        shutil.rmtree(d)
        assert r.returncode == 0, f"Testbench compilation failed:\n{r.stderr}"


# ---------------------------------------------------------------------------
# Bug-fix verification
# ---------------------------------------------------------------------------

class TestBugFixes:
    def test_shift_bug_fixed(self):
        """SHL by 16 on WIDTH=32 must produce 65536 (requires >4-bit shift amount)."""
        r, d = run_nvc(
            "-a", "/app/alu.vhd", "/tests/verify_shift.vhd",
            "-e", "verify_shift", "-r",
        )
        shutil.rmtree(d)
        assert r.returncode == 0, (
            f"Shift bug not fixed – SHL/SHR with shift>15 fails:\n{r.stderr}"
        )

    def test_overflow_bug_fixed(self):
        """SUB 0x80-0x01 (signed -128-1) must set the overflow flag."""
        r, d = run_nvc(
            "-a", "/app/alu.vhd", "/tests/verify_ovf.vhd",
            "-e", "verify_ovf", "-r",
        )
        shutil.rmtree(d)
        assert r.returncode == 0, (
            f"Overflow bug not fixed – SUB overflow flag incorrect:\n{r.stderr}"
        )

    def test_mul_carry_bug_fixed(self):
        """MUL overflow with carry in upper product bits must set carry flag."""
        r, d = run_nvc(
            "-a", "/app/alu.vhd", "/tests/verify_mul.vhd",
            "-e", "verify_mul", "-r",
        )
        shutil.rmtree(d)
        assert r.returncode == 0, (
            f"MUL carry bug not fixed – carry flag not set for upper-bit overflow:\n{r.stderr}"
        )


# ---------------------------------------------------------------------------
# Simulation at multiple widths
# ---------------------------------------------------------------------------

class TestSimulation:
    @pytest.mark.parametrize("width", [8, 16, 32])
    def test_simulation_passes(self, width):
        r, d = run_nvc(
            "-a", "/app/alu.vhd", "/app/tb_alu.vhd",
            "-e", f"-gWIDTH={width}", "tb_alu", "-r",
        )
        shutil.rmtree(d)
        assert r.returncode == 0, (
            f"Simulation failed for WIDTH={width}:\n{r.stderr}"
        )


# ---------------------------------------------------------------------------
# Testbench completeness
# ---------------------------------------------------------------------------

class TestTestbenchCompleteness:
    def test_all_operations_present(self):
        with open("/app/tb_alu.vhd") as f:
            src = f.read()
        for opname in [
            "OP_ADD", "OP_SUB", "OP_AND", "OP_OR", "OP_XOR",
            "OP_SHL", "OP_SHR", "OP_NOT", "OP_CMP", "OP_MUL",
        ]:
            assert opname in src, f"Testbench does not reference {opname}"


# ---------------------------------------------------------------------------
# Coverage pipeline
# ---------------------------------------------------------------------------

class TestCoveragePipeline:
    def test_script_exists_and_executable(self):
        assert os.path.isfile("/app/run_coverage.sh"), "run_coverage.sh missing"
        assert os.access("/app/run_coverage.sh", os.X_OK), "run_coverage.sh not executable"

    def test_pipeline_produces_outputs(self):
        """Run the coverage script and verify all expected artefacts."""
        # Clean previous artefacts so we know the script creates them
        for f in ["merged.ncdb"]:
            p = os.path.join("/app", f)
            if os.path.exists(p):
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        rpt = "/app/coverage_report"
        if os.path.isdir(rpt):
            shutil.rmtree(rpt)

        r = subprocess.run(
            ["bash", "/app/run_coverage.sh"],
            capture_output=True, text=True, cwd="/app", timeout=300,
        )
        assert r.returncode == 0, (
            f"Coverage pipeline failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        assert os.path.isfile("/app/merged.ncdb"), "merged.ncdb not created"
        assert os.path.isfile("/app/coverage_report/index.html"), (
            "coverage_report/index.html not created"
        )

    def test_statement_coverage_threshold(self):
        """Merged coverage must show >=90 % statement coverage."""
        if not os.path.isfile("/app/merged.ncdb"):
            pytest.skip("merged.ncdb missing – pipeline test must run first")

        outdir = tempfile.mkdtemp()
        r = subprocess.run(
            ["nvc", "--cover-report", "-o", outdir, "/app/merged.ncdb"],
            capture_output=True, text=True, cwd="/app", timeout=60,
        )
        output = r.stdout + "\n" + r.stderr
        shutil.rmtree(outdir, ignore_errors=True)

        matches = re.findall(r"statement:\s+([\d.]+)\s*%", output)
        assert matches, f"Could not parse statement coverage from NVC output:\n{output}"

        best = max(float(m) for m in matches)
        assert best >= 90.0, (
            f"Best statement coverage is {best}% (need >=90%)"
        )
