"""Tests for the 8086 decoder-simulator-cycle-estimator pipeline.

Round-trip decode tests verify that decoded assembly reassembles via NASM
to produce a binary identical to the original input.
Simulation tests verify correct execution state and cycle counts.
"""

import subprocess
import json
import os
import pytest

SIM = "/app/sim86.py"
PROG = "/app/programs"

ALL_BINS = sorted(f for f in os.listdir(PROG) if f.endswith(".bin"))


def run_decode(binary):
    r = subprocess.run(
        ["python3", SIM, "decode", f"{PROG}/{binary}"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"Decode failed for {binary}:\n{r.stderr}"
    return r.stdout


def run_exec(binary):
    r = subprocess.run(
        ["python3", SIM, "exec", f"{PROG}/{binary}"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, (
        f"Exec failed for {binary}:\nstderr: {r.stderr}\nstdout: {r.stdout}"
    )
    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Output is not valid JSON:\n{r.stdout}")


def check_state(binary, expected):
    state = run_exec(binary)
    # IP must equal binary file length (execution runs from 0 to end of program)
    bin_size = os.path.getsize(f"{PROG}/{binary}")
    assert state["ip"] == bin_size, (
        f"{binary}: ip expected {bin_size} (file size), got {state['ip']}"
    )
    for key, val in expected.items():
        assert state[key] == val, (
            f"{binary}: {key} expected {val!r}, got {state[key]!r}"
        )


# ---------------------------------------------------------------------------
# Round-trip decode tests: decode -> NASM reassemble -> binary compare
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("binary", ALL_BINS)
def test_roundtrip_decode(binary, tmp_path):
    asm_text = run_decode(binary)

    asm_file = tmp_path / "decoded.asm"
    asm_file.write_text(asm_text)

    rt_bin = tmp_path / "roundtrip.bin"
    r = subprocess.run(
        ["nasm", "-f", "bin", str(asm_file), "-o", str(rt_bin)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"NASM reassembly failed for {binary}:\n{r.stderr}\n"
        f"Decoded ASM:\n{asm_text}"
    )

    orig = open(f"{PROG}/{binary}", "rb").read()
    rt = rt_bin.read_bytes()

    assert orig == rt, (
        f"Round-trip mismatch for {binary}\n"
        f"Original  ({len(orig)} bytes): {orig.hex()}\n"
        f"Roundtrip ({len(rt)} bytes): {rt.hex()}"
    )


# ---------------------------------------------------------------------------
# Simulation + cycle estimation tests
# ---------------------------------------------------------------------------

def test_prog1_movs():
    """8 immediate MOV to registers, each 4 clocks."""
    check_state("prog1_movs.bin", {
        "ax": 1, "bx": 2, "cx": 3, "dx": 4,
        "sp": 5, "bp": 6, "si": 7, "di": 8,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": False,
        "total_clocks": 32,
    })


def test_prog2_arithmetic():
    """Register arithmetic: ADD/SUB/CMP/MOV with register and immediate forms."""
    check_state("prog2_arithmetic.bin", {
        "ax": 150, "bx": 30, "cx": 120, "dx": 30,
        "sp": 0, "bp": 0, "si": 0, "di": 0,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": True,
        "total_clocks": 26,
    })


def test_prog3_fibonacci():
    """Fibonacci loop: JNZ taken/not-taken cycle difference."""
    check_state("prog3_fibonacci.bin", {
        "ax": 55, "bx": 89, "cx": 0, "dx": 89,
        "sp": 0, "bp": 0, "si": 0, "di": 0,
        "CF": False, "ZF": True, "SF": False, "OF": False, "PF": True,
        "total_clocks": 290,
    })


def test_prog4_memory():
    """Direct memory addressing: moffs and modrm direct EA costs."""
    check_state("prog4_memory.bin", {
        "ax": 0x1234, "bx": 0x5678, "cx": 0x68AC, "dx": 0x5678,
        "sp": 0, "bp": 0, "si": 0x68AC, "di": 0,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": True,
        "total_clocks": 93,
    })


def test_prog5_sum_loop():
    """Sum 1..100 via LOOP: LOOP taken=17/not-taken=5 + direct memory stores."""
    check_state("prog5_sum_loop.bin", {
        "ax": 5050, "bx": 5050, "cx": 0, "dx": 0xFC46,
        "sp": 0, "bp": 0, "si": 0xFC46, "di": 0,
        "CF": True, "ZF": False, "SF": True, "OF": False, "PF": False,
        "total_clocks": 2034,
    })


def test_prog6_indexed():
    """[BX+SI] base+index EA cost for stores, loads, and immediate-to-memory."""
    check_state("prog6_indexed.bin", {
        "ax": 0x1515, "bx": 0x0100, "cx": 0x0B0B, "dx": 0,
        "sp": 0, "bp": 0, "si": 2, "di": 0,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": False,
        "total_clocks": 108,
    })


def test_prog7_byte_ops():
    """Byte-width MOV, [BP+DI] vs [BP+DI+disp] EA costs, INC/DEC timing."""
    check_state("prog7_byte_ops.bin", {
        "ax": 0x4241, "bx": 0x4443, "cx": 0x4241, "dx": 0x4241,
        "sp": 0, "bp": 0x0100, "si": 0, "di": 8,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": True,
        "total_clocks": 100,
    })


def test_prog8_ea_timing():
    """EA asymmetry: [BX+DI]=8 vs [BX+SI]=7, [BP+SI+d]=12 vs [BP+DI+d]=11,
    ADD mem,reg (16+EA) vs MOV mem,reg (9+EA)."""
    check_state("prog8_ea_timing.bin", {
        "ax": 2023, "bx": 0x0400, "cx": 0, "dx": 999,
        "sp": 0, "bp": 0x0500, "si": 0, "di": 16,
        "CF": False, "ZF": False, "SF": False, "OF": False, "PF": True,
        "total_clocks": 172,
    })
