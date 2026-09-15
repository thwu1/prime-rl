
"""
Verification tests for the pipelined compute module.
Runs the Icarus Verilog simulation and checks for PASS.
"""

import subprocess
import os
import pytest


WORKDIR = "/app"


def run_simulate():
    """Run the simulate script and return (stdout+stderr, returncode)."""
    result = subprocess.run(
        ["bash", "./simulate"],
        cwd=WORKDIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + "\n" + result.stderr
    return combined, result.returncode


class TestComputeModule:
    """Tests for the pipelined compute module with flow control."""

    def test_compute_sv_exists(self):
        """compute.sv must exist and contain meaningful content."""
        path = os.path.join(WORKDIR, "compute.sv")
        assert os.path.isfile(path), "compute.sv does not exist"
        with open(path) as f:
            content = f.read()
        # Must have real implementation (not just the empty skeleton)
        assert "pipe_" in content or "always" in content, \
            "compute.sv appears to be empty / unimplemented"

    def test_compilation_succeeds(self):
        """The design must compile without errors under iverilog -g2012."""
        result = subprocess.run(
            ["iverilog", "-g2012",
             "arithmetic_blocks/pipe_add.sv",
             "arithmetic_blocks/pipe_sub.sv",
             "arithmetic_blocks/pipe_mult.sv",
             "arithmetic_blocks/pipe_isqrt.sv",
             "compute.sv",
             "testbench.sv",
             "-o", "/tmp/compile_check.vvp"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = result.stdout + "\n" + result.stderr
        assert result.returncode == 0, \
            f"Compilation failed:\n{combined}"
        # Clean up
        if os.path.exists("/tmp/compile_check.vvp"):
            os.remove("/tmp/compile_check.vvp")

    def test_simulation_passes(self):
        """Full simulation must produce PASS with no FAIL."""
        output, _ = run_simulate()
        assert "FAIL" not in output, \
            f"Simulation reported FAIL:\n{output}"
        assert "PASS" in output, \
            f"Simulation did not report PASS:\n{output}"

    def test_no_compilation_failure(self):
        """simulate script must not report compilation failure."""
        output, rc = run_simulate()
        assert "COMPILATION FAILED" not in output, \
            f"Compilation failed:\n{output}"
