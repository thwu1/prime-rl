"""
Tests for the flow control wrapper task.

Verifies that the wrapper compiles, simulates correctly,
and passes all testbench checks.

"""

import subprocess
import os
import pytest


def _run(cmd, timeout=120):
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/app",
    )


def test_compilation():
    """Design compiles without errors under Icarus Verilog."""
    result = _run([
        "iverilog", "-g2012",
        "rtl/blackbox/pipe_mult.sv",
        "rtl/blackbox/pipe_add.sv",
        "rtl/blackbox/pipe_isqrt.sv",
        "rtl/compute_pipeline.sv",
        "rtl/flow_control_wrapper.sv",
        "tb/tb_flow_control.sv",
        "-o", "/tmp/compile_check",
    ], timeout=30)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"Compilation failed (rc={result.returncode}):\n{combined}"
    )


def test_simulation_pass():
    """Simulation runs and produces PASS with no FAIL."""
    result = _run(["bash", "/app/simulate.sh"], timeout=120)
    output = result.stdout + result.stderr
    assert "FAIL" not in output, f"Simulation produced FAIL:\n{output}"
    assert "PASS" in output, f"PASS not found in simulation output:\n{output}"


def test_wrapper_instantiates_pipeline():
    """The wrapper must instantiate compute_pipeline (not bypass it)."""
    wrapper_path = "/app/rtl/flow_control_wrapper.sv"
    assert os.path.exists(wrapper_path), "flow_control_wrapper.sv not found"
    with open(wrapper_path, "r") as f:
        src = f.read()
    assert "compute_pipeline" in src, (
        "Wrapper must instantiate compute_pipeline module"
    )


def test_wrapper_has_buffering():
    """The wrapper should contain buffering/queuing logic."""
    wrapper_path = "/app/rtl/flow_control_wrapper.sv"
    with open(wrapper_path, "r") as f:
        lines = f.readlines()
    # Strip comments and blank lines, keep only code
    code_lines = []
    for line in lines:
        stripped = line.split("//")[0].strip()
        if stripped:
            code_lines.append(stripped.lower())
    code = " ".join(code_lines)
    has_buffer = any(kw in code for kw in [
        "wr_ptr", "rd_ptr", "write_ptr", "read_ptr",
        "w_ptr", "r_ptr", "wptr", "rptr", "fifo_mem",
        "head", "tail", "buf_mem", "queue_mem",
    ])
    assert has_buffer, (
        "Wrapper should contain buffering logic (memory arrays or pointers)"
    )
