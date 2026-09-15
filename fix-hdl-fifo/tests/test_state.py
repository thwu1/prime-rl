
import subprocess
import os
import pytest

OBJ_DIR = "/tmp/tb_obj_dir"

RTL_FILES = ["fifo_pkg.sv", "fifo_mem.sv", "fifo_ctrl.sv", "fifo.sv",
             "dual_fifo_arb.sv", "arbiter.sv"]


def test_rtl_files_exist():
    """All RTL source files must exist, including the solver-created arbiter."""
    for f in RTL_FILES:
        path = f"/app/rtl/{f}"
        assert os.path.isfile(path), f"Missing RTL file: {path}"


def test_arbiter_has_required_ports():
    """Arbiter module must declare the required port interface."""
    with open("/app/rtl/arbiter.sv") as fh:
        content = fh.read()
    assert "module arbiter" in content, "arbiter.sv must define 'module arbiter'"
    for port in ["ch_a_data", "ch_a_valid", "ch_a_ready",
                 "ch_b_data", "ch_b_valid", "ch_b_ready",
                 "out_data", "out_valid", "out_ready"]:
        assert port in content, f"arbiter.sv must declare port '{port}'"


def test_module_names_preserved():
    """Original module/package names must be preserved in each file."""
    expected = {
        "fifo_pkg.sv": "package fifo_pkg",
        "fifo_mem.sv": "module fifo_mem",
        "fifo_ctrl.sv": "module fifo_ctrl",
        "fifo.sv": "module fifo",
        "dual_fifo_arb.sv": "module dual_fifo_arb",
    }
    for fname, pattern in expected.items():
        with open(f"/app/rtl/{fname}") as fh:
            content = fh.read()
        assert pattern in content, (
            f"{fname} must contain '{pattern}' — "
            f"do not rename modules or replace files entirely"
        )


def test_verilator_compilation():
    """Full system must compile with Verilator without errors."""
    subprocess.run(["rm", "-rf", OBJ_DIR], check=False)

    result = subprocess.run(
        [
            "verilator", "--binary", "--timing",
            "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC",
            "rtl/fifo_pkg.sv", "rtl/fifo_mem.sv",
            "rtl/fifo_ctrl.sv", "rtl/fifo.sv",
            "rtl/dual_fifo_arb.sv", "rtl/arbiter.sv",
            "/tests/tb_dual_fifo_arb.sv",
            "--top-module", "tb_dual_fifo_arb",
            "--Mdir", OBJ_DIR,
        ],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Verilator compilation failed (rc={result.returncode}):\n"
        f"{result.stderr[:3000]}"
    )


def test_simulation_passes():
    """Simulation must run to completion and report PASS."""
    binary = os.path.join(OBJ_DIR, "Vtb_dual_fifo_arb")
    assert os.path.isfile(binary), (
        "Simulation binary not found — Verilator compilation must succeed first."
    )

    result = subprocess.run(
        [binary],
        capture_output=True,
        text=True,
        timeout=60,
    )

    stdout = result.stdout

    # Check for the PASS marker
    assert "PASS: All tests passed" in stdout, (
        f"Simulation did not pass.\nOutput:\n{stdout[:3000]}"
    )

    # Ensure no FAIL lines exist
    fail_lines = [
        line for line in stdout.strip().split("\n")
        if line.startswith("FAIL:")
    ]
    assert len(fail_lines) == 0, (
        f"Simulation reported failures:\n" + "\n".join(fail_lines)
    )
