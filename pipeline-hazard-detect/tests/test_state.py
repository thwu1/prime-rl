"""
Verification tests for MaxiCore32 pipeline hazard detection.

Each test assembles a small program (as raw hex instruction words), loads it into
the simulation memory, runs the processor via iverilog/vvp, and checks that the
register file contains the expected values at HALT.

Without hazard detection, tests 1-3 and 5 produce incorrect register values because
the pipeline reads stale data. Test 4 is a sanity check with independent registers.
"""


import subprocess
import os
import re
import pytest

APP_DIR = "/app"
RAM_FILE = os.path.join(APP_DIR, "maxicore32-ram-contents.txt")
TB_BIN = os.path.join(APP_DIR, "maxicore32_tb")
TOTAL_WORDS = 1024


def write_ram(program):
    """Write a program (list of 32-bit ints) to the RAM contents file."""
    with open(RAM_FILE, "w") as f:
        for i in range(TOTAL_WORDS):
            if i < len(program):
                f.write(f"{program[i]:08x}\n")
            else:
                f.write("00000000\n")


def run_simulation():
    """Run the vvp simulation and return stdout."""
    result = subprocess.run(
        ["vvp", TB_BIN],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=APP_DIR,
    )
    return result.stdout, result.stderr, result.returncode


def parse_registers(output):
    """Parse register values from the simulation register dump."""
    regs = {}
    in_regs = False
    for line in output.split("\n"):
        if "=== REGISTERS ===" in line:
            in_regs = True
            continue
        if in_regs:
            if "===" in line and "REGISTERS" not in line:
                break
            for match in re.finditer(r"r(\d+)\s*=\s+([0-9a-fA-F]+)", line):
                reg_num = int(match.group(1))
                reg_val = int(match.group(2), 16)
                regs[f"r{reg_num}"] = reg_val
    return regs


def run_test_program(program, expected_regs, description=""):
    """Write program to RAM, simulate, and verify register state."""
    write_ram(program)
    stdout, stderr, rc = run_simulation()

    assert "HALTED" in stdout, (
        f"Simulation did not halt. Last 500 chars of output:\n{stdout[-500:]}"
    )
    assert "BUS ERROR" not in stdout, "Bus error occurred during simulation"

    regs = parse_registers(stdout)
    assert len(regs) > 0, (
        f"Could not parse register dump from output:\n{stdout[-500:]}"
    )

    for reg, expected in expected_regs.items():
        actual = regs.get(reg)
        assert actual is not None, f"Register {reg} not found in output"
        assert actual == expected, (
            f"[{description}] Register {reg}: "
            f"expected {expected} (0x{expected:08x}), "
            f"got {actual} (0x{actual:08x})"
        )


# ── ISA encoding reference ──────────────────────────────────────────
# loadi.u rD, imm16  -> 0b00010_100_DDDD_0000_IIIIIIIIIIIIIIII
# add rD, rA, rO     -> 0b00111_000_DDDD_AAAA_0000_OOOO_00000000
# compare rD, rA, rO -> 0b00111_000_DDDD_AAAA_0111_OOOO_00000000
# branch.eq target   -> 0b01010_000_0000_off[15:12]_0001_off[11:0]
# store.l off(rA),rD -> 0b00100_000_DDDD_AAAA_off[15:0]
# load.l rD,off(rA)  -> 0b00011_000_DDDD_AAAA_off[15:0]
# halt               -> 0b00001_000_00000000_00000000_00000000
# nop                -> 0b00000_000_00000000_00000000_00000000


def test_loadi_alu_data_hazard():
    """LOADI immediately followed by ALU use: register RAW hazard on r1.

    Without hazard detection the ALU reads stale r1 (=0), giving r0=0.
    With hazard detection, a stall lets r1=5 commit, giving r0=10.
    """
    program = [
        0x14100005,  # loadi.u r1, 5
        0x38010100,  # add r0, r1, r1
        0x08000000,  # halt
    ]
    run_test_program(program, {"r0": 10, "r1": 5},
                     "loadi->ALU data hazard")


def test_alu_branch_status_hazard():
    """ALU compare followed by conditional branch: status flag hazard.

    compare r1,r1,r2 sets zero flag; branch.eq must see it.
    Also exercises a data hazard between loadi r2 and compare (reads r2).
    """
    program = [
        0x14100005,  # loadi.u r1, 5
        0x14200005,  # loadi.u r2, 5
        0x38117200,  # compare r1, r1, r2   (ALUM: OP_COMP=0x7)
        0x50001008,  # branch.eq .pass      (offset=8 -> target 0x18)
        0x14000000,  # loadi.u r0, 0        (fail path)
        0x08000000,  # halt                 (fail)
        0x1400002A,  # .pass: loadi.u r0, 42
        0x08000000,  # halt                 (pass)
    ]
    run_test_program(program, {"r0": 42},
                     "ALU->branch status hazard")


def test_chained_alu_hazards():
    """Three consecutive ALU ops each depending on the previous result.

    loadi r1,3 -> add r2,r1,r1 -> add r3,r2,r1 -> add r0,r3,r1
    Each add has a RAW hazard on the destination of the prior instruction.
    """
    program = [
        0x14100003,  # loadi.u r1, 3
        0x38210100,  # add r2, r1, r1   (r2 = 6)
        0x38320100,  # add r3, r2, r1   (r3 = 9)
        0x38030100,  # add r0, r3, r1   (r0 = 12)
        0x08000000,  # halt
    ]
    run_test_program(program, {"r0": 12, "r1": 3, "r2": 6, "r3": 9},
                     "chained ALU hazards")


def test_independent_registers_no_stall():
    """Independent register ops: no hazard should be detected.

    Three consecutive LOADIs to different registers followed by an ADD
    that reads r1 and r2 while stage 2 writes r3 — no conflict.
    """
    program = [
        0x1410000A,  # loadi.u r1, 10
        0x14200014,  # loadi.u r2, 20
        0x1430001E,  # loadi.u r3, 30
        0x38010200,  # add r0, r1, r2   (r0 = 30)
        0x08000000,  # halt
    ]
    run_test_program(program, {"r0": 30, "r1": 10, "r2": 20, "r3": 30},
                     "independent registers (no hazard)")


def test_store_address_hazard():
    """Store instruction with address register just written by LOADI.

    Without hazard detection the store uses the stale r5 value (0) as the
    address, so the value is written to address 0 instead of 64.  The
    subsequent load from address 64 returns 0 instead of 99.
    """
    program = [
        0x14100063,  # loadi.u r1, 99
        0x14500040,  # loadi.u r5, 64
        0x20150000,  # store.l 0(r5), r1
        0x18050000,  # load.l r0, 0(r5)
        0x08000000,  # halt
    ]
    run_test_program(program, {"r0": 99},
                     "store address hazard")
