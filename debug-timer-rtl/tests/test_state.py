
import subprocess
import os
import tempfile
import pytest


def compile_and_run(rtl_path, tb_path="/app/tb/tb_verify.v"):
    """Compile RTL with testbench using Icarus Verilog and run simulation."""
    with tempfile.NamedTemporaryFile(suffix=".vvp", delete=False) as f:
        out_path = f.name
    try:
        comp = subprocess.run(
            ["iverilog", "-o", out_path, rtl_path, tb_path],
            capture_output=True, text=True, timeout=60,
        )
        if comp.returncode != 0:
            return None, comp.stderr
        sim = subprocess.run(
            ["vvp", out_path],
            capture_output=True, text=True, timeout=180,
        )
        return sim.stdout, sim.stderr
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


class TestVerificationTestbench:
    """Verify the solver's testbench achieves 100% mutation kill score."""

    def test_testbench_exists(self):
        """Testbench file must exist at /app/tb/tb_verify.v."""
        assert os.path.isfile("/app/tb/tb_verify.v"), \
            "Testbench not found at /app/tb/tb_verify.v"

    def test_testbench_instantiates_timer(self):
        """Testbench must instantiate the timer_apb module."""
        with open("/app/tb/tb_verify.v", "r") as f:
            src = f.read()
        assert "timer_apb" in src, \
            "Testbench does not reference timer_apb module"

    def test_golden_compiles(self):
        """Golden RTL must compile with the testbench without errors."""
        output, err = compile_and_run("/app/rtl/timer_apb.v")
        assert output is not None, f"Golden RTL compilation failed:\n{err}"

    def test_golden_no_failures(self):
        """Golden RTL simulation must produce zero [FAIL] lines."""
        output, _ = compile_and_run("/app/rtl/timer_apb.v")
        assert output is not None, "Golden compilation failed"
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) == 0, \
            f"Golden RTL had {len(fail_lines)} failure(s):\n" + "\n".join(fail_lines)

    def test_golden_all_passed(self):
        """Golden RTL simulation must print ALL TESTS PASSED."""
        output, _ = compile_and_run("/app/rtl/timer_apb.v")
        assert output is not None, "Golden compilation failed"
        assert "ALL TESTS PASSED" in output, \
            f"ALL TESTS PASSED not found in output:\n{output}"

    def test_minimum_check_count(self):
        """Testbench must have at least 15 individually reported checks."""
        output, _ = compile_and_run("/app/rtl/timer_apb.v")
        assert output is not None, "Golden compilation failed"
        pass_lines = [l for l in output.splitlines() if "[PASS]" in l]
        assert len(pass_lines) >= 15, \
            f"Only {len(pass_lines)} [PASS] checks found; need >= 15"

    def test_mutant_1_killed(self):
        """Mutant 1 (prescaler off-by-one) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_1.v")
        if output is None:
            return  # compilation failure = killed
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 1 survived — no [FAIL] in output:\n{output}"

    def test_mutant_2_killed(self):
        """Mutant 2 (auto-reload to cmp instead of 0) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_2.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 2 survived — no [FAIL] in output:\n{output}"

    def test_mutant_3_killed(self):
        """Mutant 3 (W1C logic inversion) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_3.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 3 survived — no [FAIL] in output:\n{output}"

    def test_mutant_4_killed(self):
        """Mutant 4 (read mux CH0/CH1 counter swap) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_4.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 4 survived — no [FAIL] in output:\n{output}"

    def test_mutant_5_killed(self):
        """Mutant 5 (capture edge polarity inversion) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_5.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 5 survived — no [FAIL] in output:\n{output}"

    def test_mutant_6_killed(self):
        """Mutant 6 (CH1 match event suppressed) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_6.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 6 survived — no [FAIL] in output:\n{output}"

    def test_mutant_7_killed(self):
        """Mutant 7 (overflow counter non-wrap) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_7.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 7 survived — no [FAIL] in output:\n{output}"

    def test_mutant_8_killed(self):
        """Mutant 8 (IRQ ignores enable mask) must be detected."""
        output, err = compile_and_run("/app/mutants/mutant_8.v")
        if output is None:
            return
        fail_lines = [l for l in output.splitlines() if "[FAIL]" in l]
        assert len(fail_lines) > 0, \
            f"Mutant 8 survived — no [FAIL] in output:\n{output}"

    def test_golden_rtl_unchanged(self):
        """Golden RTL must not have been tampered with."""
        with open("/app/rtl/timer_apb.v", "r") as f:
            src = f.read()
        assert "module timer_apb" in src, "Golden RTL missing module declaration"
        assert "prescaler_cnt >= prescaler_div" in src, \
            "Golden RTL prescaler comparison appears modified"
        assert "& ~pwdata[3:0]" in src, \
            "Golden RTL W1C logic appears modified"
        assert "int_flag[3:0] & int_en[3:0]" in src, \
            "Golden RTL IRQ logic appears modified"
