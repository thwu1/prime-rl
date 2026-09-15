
"""
Tests for the 6502 emulator:
  1. Compilation test
  2. Klaus2m5 functional test suite (all opcodes, flags, BCD)
  3. Cycle-count accuracy tests
  4. BCD exhaustive verification (ADC decimal mode, all 131072 inputs)
"""

import subprocess
import os
import re
import pytest

APP_DIR = "/app"
EMU = os.path.join(APP_DIR, "emu6502")
TESTS_DIR = os.path.join(APP_DIR, "tests")
KLAUS_BIN = os.path.join(TESTS_DIR, "6502_functional_test.bin")


@pytest.fixture(scope="session", autouse=True)
def compile_emulator():
    """Compile the emulator before running any tests."""
    result = subprocess.run(
        ["make", "clean"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["make"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Compilation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    assert os.path.isfile(EMU), "Emulator binary not found after compilation"


class TestKlausFunctional:
    """Run the Klaus2m5 6502 functional test suite."""

    def test_klaus_functional_test_passes(self):
        """The emulator must pass the Klaus functional test suite.

        The test binary is loaded at $0000 with entry at $0400.
        Success is verified by confirming that:
        1. The emulator terminates via a JMP-to-self trap (not timeout).
        2. The trap instruction is indeed a JMP ($4C) targeting itself.
        3. The emulator executed >= 25 million instructions, confirming
           the full test suite ran to completion.  A successful run
           executes ~30M instructions; any failure traps well below
           this threshold.
        """
        assert os.path.isfile(KLAUS_BIN), (
            f"Klaus test binary not found at {KLAUS_BIN}"
        )

        result = subprocess.run(
            [EMU, KLAUS_BIN, "0000", "0400", "--cycles"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = result.stdout

        # Emulator must exit cleanly (code 0 = trap hit)
        assert result.returncode == 0, (
            f"Emulator exited with error.\n"
            f"Return code: {result.returncode}\n"
            f"STDOUT: {stdout}\n"
            f"STDERR: {result.stderr}"
        )

        # Must have hit a trap
        assert "TRAP at" in stdout, (
            f"No trap detected in emulator output.\n"
            f"STDOUT: {stdout}\n"
            f"STDERR: {result.stderr}"
        )

        # Parse the trap address and verify it is a JMP-to-self
        trap_match = re.search(r'TRAP at \$([0-9A-Fa-f]+)', stdout)
        assert trap_match, (
            f"Could not parse trap address.\nSTDOUT: {stdout}"
        )
        trap_addr = int(trap_match.group(1), 16)

        with open(KLAUS_BIN, "rb") as f:
            data = f.read()
        assert trap_addr + 2 < len(data), (
            f"Trap address ${trap_addr:04X} is outside the binary"
        )
        assert data[trap_addr] == 0x4C, (
            f"Byte at trap address ${trap_addr:04X} is "
            f"${data[trap_addr]:02X}, not $4C (JMP)"
        )
        jmp_target = data[trap_addr + 1] | (data[trap_addr + 2] << 8)
        assert jmp_target == trap_addr, (
            f"Instruction at ${trap_addr:04X} jumps to "
            f"${jmp_target:04X}, not itself"
        )

        # Parse instruction count — the full Klaus suite executes ~30M
        # instructions.  Any failure would trap much earlier.
        instr_match = re.search(r'instructions=(\d+)', stdout)
        assert instr_match, (
            f"Could not parse instruction count.\nSTDOUT: {stdout}"
        )
        instr_count = int(instr_match.group(1))

        MIN_INSTRUCTIONS = 25_000_000
        assert instr_count >= MIN_INSTRUCTIONS, (
            f"Only {instr_count} instructions executed — test failed "
            f"early (expected >={MIN_INSTRUCTIONS} for full suite).\n"
            f"Trap at ${trap_addr:04X}\n"
            f"STDOUT: {stdout}"
        )


class TestCycleCounts:
    """Verify per-instruction cycle-count accuracy."""

    def _run_cycle_test(self, bin_name, expected_cycles):
        bin_path = os.path.join(TESTS_DIR, bin_name)
        assert os.path.isfile(bin_path), f"Test binary {bin_name} not found"
        result = subprocess.run(
            [EMU, bin_path, "0400", "0400", "--cycles"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = result.stdout
        # Parse cycles=NNN from output
        for line in stdout.split("\n"):
            if line.startswith("cycles="):
                parts = line.split()
                actual = int(parts[0].split("=")[1])
                assert actual == expected_cycles, (
                    f"{bin_name}: expected {expected_cycles} cycles, got {actual}\n"
                    f"Full output: {stdout}"
                )
                return
        pytest.fail(f"{bin_name}: no cycle count in output.\n{stdout}\n{result.stderr}")

    def test_nop_timing(self):
        self._run_cycle_test("test_nop_timing.bin", 13)

    def test_lda_imm(self):
        self._run_cycle_test("test_lda_imm.bin", 7)

    def test_branch_taken(self):
        self._run_cycle_test("test_branch_taken.bin", 8)

    def test_branch_not_taken(self):
        self._run_cycle_test("test_branch_not_taken.bin", 7)

    def test_stack_ops(self):
        self._run_cycle_test("test_stack_ops.bin", 10)

    def test_jsr_rts(self):
        self._run_cycle_test("test_jsr_rts.bin", 15)

    def test_abs_x_page_cross(self):
        self._run_cycle_test("test_abs_x_page_cross.bin", 10)

    def test_abs_x_no_cross(self):
        self._run_cycle_test("test_abs_x_no_cross.bin", 9)

    def test_zp_ops(self):
        self._run_cycle_test("test_zp_ops.bin", 16)

    def test_flag_ops(self):
        self._run_cycle_test("test_flag_ops.bin", 17)


class TestBCDExhaustive:
    """Exhaustive BCD ADC verification against a reference implementation.

    Tests all 256*256*2 = 131072 input combinations for ADC in decimal mode
    by running a test binary that computes and stores results, then comparing
    against a Python reference.
    """

    @staticmethod
    def _ref_adc_bcd(a, b, carry_in):
        """Reference NMOS 6502 BCD ADC implementation.

        Returns (result, C, Z, N, V) with NMOS flag behavior:
        - Z is based on the BINARY (not decimal) addition
        - N is set from bit 7 of the intermediate decimal result (after
          low-nibble correction, before high-nibble correction) — this
          matches the NMOS 6502 ALU pipeline
        - V is based on the binary addition
        - C is based on the decimal result
        """
        # Binary result (for V, Z flags)
        bin_result = a + b + carry_in
        bin_z = 1 if (bin_result & 0xFF) == 0 else 0
        # V: set if sign of result differs from sign of both operands
        bin_v = 1 if (~(a ^ b) & (a ^ bin_result)) & 0x80 else 0

        # Decimal result
        lo = (a & 0x0F) + (b & 0x0F) + carry_in
        hi_carry = 0
        if lo > 9:
            lo -= 10
            hi_carry = 1
        hi = (a >> 4) + (b >> 4) + hi_carry

        # N from intermediate: after low nibble correction, before high
        partial = ((hi & 0xFF) << 4) | (lo & 0x0F)
        bin_n = 1 if (partial & 0x80) else 0

        if hi > 9:
            hi -= 10
            carry_out = 1
        else:
            carry_out = 0

        result = ((hi & 0x0F) << 4) | (lo & 0x0F)
        return result, carry_out, bin_z, bin_n, bin_v

    def test_bcd_adc_exhaustive(self):
        """Build and run a C program that exercises BCD ADC exhaustively,
        then compare results against the Python reference."""

        # Write a C test harness that uses the emulator's ADC implementation
        bcd_test_c = r"""
/* Exhaustive BCD ADC tester — outputs results for all 131072 combos */
#include <stdio.h>
#include <string.h>
#include "cpu6502.h"

int main(void) {
    cpu6502_t cpu;
    /* For each (a, b, carry_in), set up state and execute ADC */
    for (int carry = 0; carry <= 1; carry++) {
        for (int a = 0; a < 256; a++) {
            for (int b = 0; b < 256; b++) {
                cpu_init(&cpu);
                /* Place ADC #imm at $0400, trap at $0402 */
                cpu.memory[0x0400] = 0x69; /* ADC #imm */
                cpu.memory[0x0401] = (uint8_t)b;
                cpu.memory[0x0402] = 0x4C; /* JMP $0402 */
                cpu.memory[0x0403] = 0x02;
                cpu.memory[0x0404] = 0x04;
                cpu.PC = 0x0400;
                cpu.A  = (uint8_t)a;
                cpu.P  = FLAG_U | FLAG_D; /* decimal mode on */
                if (carry) cpu.P |= FLAG_C;

                cpu_step(&cpu);

                int c_out = (cpu.P & FLAG_C) ? 1 : 0;
                int z_out = (cpu.P & FLAG_Z) ? 1 : 0;
                int n_out = (cpu.P & FLAG_N) ? 1 : 0;
                int v_out = (cpu.P & FLAG_V) ? 1 : 0;

                printf("%d %d %d %d %d %d %d %d\n",
                       a, b, carry, cpu.A, c_out, z_out, n_out, v_out);
            }
        }
    }
    return 0;
}
"""
        bcd_src = os.path.join(APP_DIR, "bcd_test.c")
        bcd_bin = os.path.join(APP_DIR, "bcd_test")
        with open(bcd_src, "w") as f:
            f.write(bcd_test_c)

        # Compile
        result = subprocess.run(
            ["gcc", "-O2", "-Wall", "-std=c11", "-o", bcd_bin,
             bcd_src, os.path.join(APP_DIR, "cpu6502.c")],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"BCD test compilation failed:\n{result.stderr}"
        )

        # Run and collect output
        result = subprocess.run(
            [bcd_bin],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"BCD test execution failed:\n{result.stderr}"
        )

        # Verify each line against reference
        errors = []
        line_count = 0
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) != 8:
                continue
            a, b, cin, got_r, got_c, got_z, got_n, got_v = map(int, parts)
            exp_r, exp_c, exp_z, exp_n, exp_v = self._ref_adc_bcd(a, b, cin)

            if (got_r != exp_r or got_c != exp_c or got_z != exp_z
                    or got_n != exp_n or got_v != exp_v):
                errors.append(
                    f"A=${a:02X} B=${b:02X} C_in={cin}: "
                    f"got(R=${got_r:02X} C={got_c} Z={got_z} N={got_n} V={got_v}) "
                    f"exp(R=${exp_r:02X} C={exp_c} Z={exp_z} N={exp_n} V={exp_v})"
                )
                if len(errors) >= 20:
                    break
            line_count += 1

        assert line_count == 131072, (
            f"Expected 131072 test lines, got {line_count}"
        )
        assert len(errors) == 0, (
            f"BCD ADC mismatches ({len(errors)} shown):\n" +
            "\n".join(errors)
        )
