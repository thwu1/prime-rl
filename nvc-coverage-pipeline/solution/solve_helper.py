#!/usr/bin/env python3
"""
Solution helper for the VHDL ALU verification task.

"""

import os
import sys
import stat


def fix_alu():
    """Fix all three bugs in /app/alu.vhd by reading, transforming, and rewriting."""
    with open("/app/alu.vhd", "r") as f:
        content = f.read()

    # Bug #1: SHL/SHR truncate shift amount to 4 bits — use full b vector
    content = content.replace("b(3 downto 0)", "b")

    # Bug #3: MUL carry checks only mul_full(WIDTH) instead of all upper bits
    content = content.replace(
        "carry <= mul_full(WIDTH);",
        "if unsigned(mul_full(2*WIDTH-1 downto WIDTH)) > 0 then\n                    carry <= '1';\n                end if;"
    )

    # Bug #2: SUB overflow detection references add_ext instead of sub_ext
    lines = content.split('\n')
    fixed_lines = []
    in_sub_case = False
    for line in lines:
        if "when OP_SUB =>" in line:
            in_sub_case = True
        elif in_sub_case and "when OP_" in line:
            in_sub_case = False
        if in_sub_case and "add_ext(WIDTH-1)" in line:
            line = line.replace("add_ext(WIDTH-1)", "sub_ext(WIDTH-1)")
        fixed_lines.append(line)

    content = '\n'.join(fixed_lines)

    with open("/app/alu.vhd", "w") as f:
        f.write(content)

    print("[solve] Fixed alu.vhd — all three bugs corrected")


def write_testbench():
    """Generate a comprehensive testbench that exercises all 10 ALU operations."""
    tb = r"""-- tb_alu.vhd: Comprehensive ALU testbench
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_alu is
    generic (
        WIDTH : positive := 8
    );
end entity;

architecture test of tb_alu is

    signal a, b, result : std_logic_vector(WIDTH-1 downto 0);
    signal op           : std_logic_vector(3 downto 0);
    signal zero, carry, ovf, neg : std_logic;

    constant OP_ADD : std_logic_vector(3 downto 0) := "0000";
    constant OP_SUB : std_logic_vector(3 downto 0) := "0001";
    constant OP_AND : std_logic_vector(3 downto 0) := "0010";
    constant OP_OR  : std_logic_vector(3 downto 0) := "0011";
    constant OP_XOR : std_logic_vector(3 downto 0) := "0100";
    constant OP_SHL : std_logic_vector(3 downto 0) := "0101";
    constant OP_SHR : std_logic_vector(3 downto 0) := "0110";
    constant OP_NOT : std_logic_vector(3 downto 0) := "0111";
    constant OP_CMP : std_logic_vector(3 downto 0) := "1000";
    constant OP_MUL : std_logic_vector(3 downto 0) := "1001";

begin
    dut: entity work.alu
        generic map (WIDTH => WIDTH)
        port map (
            a => a, b => b, op => op,
            result => result, zero => zero,
            carry => carry, ovf => ovf, neg => neg
        );

    stim: process
    begin
        -- ===== OP_ADD =====
        a <= std_logic_vector(to_unsigned(3, WIDTH));
        b <= std_logic_vector(to_unsigned(5, WIDTH));
        op <= OP_ADD;
        wait for 10 ns;
        assert unsigned(result) = 8
            report "ADD 3+5 failed" severity failure;
        assert zero = '0' report "ADD zero wrong" severity failure;

        -- ADD: zero result
        a <= (others => '0'); b <= (others => '0'); op <= OP_ADD;
        wait for 10 ns;
        assert unsigned(result) = 0 report "ADD 0+0 failed" severity failure;
        assert zero = '1' report "ADD zero flag not set" severity failure;

        -- ADD: carry
        a <= (others => '1'); b <= std_logic_vector(to_unsigned(1, WIDTH));
        op <= OP_ADD;
        wait for 10 ns;
        assert carry = '1' report "ADD carry not set" severity failure;

        -- ADD: signed overflow (positive + positive = negative)
        a <= std_logic_vector(shift_left(to_unsigned(1, WIDTH), WIDTH-2));
        b <= std_logic_vector(shift_left(to_unsigned(1, WIDTH), WIDTH-2));
        op <= OP_ADD;
        wait for 10 ns;
        assert ovf = '1' report "ADD overflow not set" severity failure;

        -- ===== OP_SUB =====
        a <= std_logic_vector(to_unsigned(10, WIDTH));
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_SUB;
        wait for 10 ns;
        assert unsigned(result) = 7 report "SUB 10-3 failed" severity failure;

        -- SUB: borrow
        a <= std_logic_vector(to_unsigned(0, WIDTH));
        b <= std_logic_vector(to_unsigned(1, WIDTH));
        op <= OP_SUB;
        wait for 10 ns;
        assert carry = '1' report "SUB borrow not set" severity failure;
        assert neg = '1' report "SUB neg flag wrong" severity failure;

        -- SUB: signed overflow (most-negative minus 1)
        a <= std_logic_vector(shift_left(to_unsigned(1, WIDTH), WIDTH-1));
        b <= std_logic_vector(to_unsigned(1, WIDTH));
        op <= OP_SUB;
        wait for 10 ns;
        assert ovf = '1' report "SUB overflow not detected" severity failure;

        -- SUB: zero result
        a <= std_logic_vector(to_unsigned(42, WIDTH));
        b <= std_logic_vector(to_unsigned(42, WIDTH));
        op <= OP_SUB;
        wait for 10 ns;
        assert zero = '1' report "SUB zero flag not set for equal values" severity failure;

        -- ===== OP_AND =====
        a <= std_logic_vector(to_unsigned(15, WIDTH));
        b <= std_logic_vector(to_unsigned(6, WIDTH));
        op <= OP_AND;
        wait for 10 ns;
        assert unsigned(result) = 6 report "AND failed" severity failure;

        -- AND: zero result
        a <= std_logic_vector(to_unsigned(0, WIDTH));
        b <= (others => '1');
        op <= OP_AND;
        wait for 10 ns;
        assert zero = '1' report "AND zero flag wrong" severity failure;

        -- ===== OP_OR =====
        a <= std_logic_vector(to_unsigned(10, WIDTH));
        b <= std_logic_vector(to_unsigned(5, WIDTH));
        op <= OP_OR;
        wait for 10 ns;
        assert unsigned(result) = 15 report "OR failed" severity failure;

        -- ===== OP_XOR =====
        a <= std_logic_vector(to_unsigned(15, WIDTH));
        b <= std_logic_vector(to_unsigned(9, WIDTH));
        op <= OP_XOR;
        wait for 10 ns;
        assert unsigned(result) = 6 report "XOR failed" severity failure;

        -- XOR: self XOR = zero
        a <= std_logic_vector(to_unsigned(42, WIDTH));
        b <= std_logic_vector(to_unsigned(42, WIDTH));
        op <= OP_XOR;
        wait for 10 ns;
        assert zero = '1' report "XOR self zero flag wrong" severity failure;

        -- ===== OP_SHL =====
        a <= std_logic_vector(to_unsigned(1, WIDTH));
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_SHL;
        wait for 10 ns;
        assert unsigned(result) = 8 report "SHL 1<<3 failed" severity failure;

        -- SHL: zero shift
        a <= std_logic_vector(to_unsigned(42, WIDTH));
        b <= std_logic_vector(to_unsigned(0, WIDTH));
        op <= OP_SHL;
        wait for 10 ns;
        assert unsigned(result) = 42 report "SHL x<<0 failed" severity failure;

        -- SHL: large shift (WIDTH/2 requires full-width shift amount)
        a <= std_logic_vector(to_unsigned(1, WIDTH));
        b <= std_logic_vector(to_unsigned(WIDTH/2, WIDTH));
        op <= OP_SHL;
        wait for 10 ns;
        assert unsigned(result) = 2**(WIDTH/2)
            report "SHL by WIDTH/2 failed" severity failure;

        -- ===== OP_SHR =====
        a <= std_logic_vector(to_unsigned(128, WIDTH));
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_SHR;
        wait for 10 ns;
        assert unsigned(result) = 16 report "SHR 128>>3 failed" severity failure;

        -- SHR: large shift
        a <= std_logic_vector(shift_left(to_unsigned(1, WIDTH), WIDTH/2));
        b <= std_logic_vector(to_unsigned(WIDTH/2, WIDTH));
        op <= OP_SHR;
        wait for 10 ns;
        assert unsigned(result) = 1
            report "SHR by WIDTH/2 failed" severity failure;

        -- SHR: shift out all bits
        a <= std_logic_vector(to_unsigned(1, WIDTH));
        b <= std_logic_vector(to_unsigned(WIDTH, WIDTH));
        op <= OP_SHR;
        wait for 10 ns;
        assert zero = '1' report "SHR shift-to-zero flag wrong" severity failure;

        -- ===== OP_NOT =====
        a <= (others => '0'); b <= (others => '0'); op <= OP_NOT;
        wait for 10 ns;
        assert result = not std_logic_vector(to_unsigned(0, WIDTH))
            report "NOT 0 failed" severity failure;
        assert neg = '1' report "NOT 0 neg flag wrong" severity failure;

        a <= (others => '1'); op <= OP_NOT;
        wait for 10 ns;
        assert unsigned(result) = 0 report "NOT all-1s failed" severity failure;
        assert zero = '1' report "NOT zero flag wrong" severity failure;

        -- ===== OP_CMP =====
        a <= std_logic_vector(to_unsigned(3, WIDTH));
        b <= std_logic_vector(to_unsigned(5, WIDTH));
        op <= OP_CMP;
        wait for 10 ns;
        assert result = not std_logic_vector(to_unsigned(0, WIDTH))
            report "CMP 3<5 should give all 1s" severity failure;

        a <= std_logic_vector(to_unsigned(5, WIDTH));
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_CMP;
        wait for 10 ns;
        assert unsigned(result) = 0
            report "CMP 5>=3 should give 0" severity failure;

        -- CMP: equal values
        a <= std_logic_vector(to_unsigned(7, WIDTH));
        b <= std_logic_vector(to_unsigned(7, WIDTH));
        op <= OP_CMP;
        wait for 10 ns;
        assert unsigned(result) = 0
            report "CMP equal should give 0" severity failure;

        -- ===== OP_MUL =====
        a <= std_logic_vector(to_unsigned(7, WIDTH));
        b <= std_logic_vector(to_unsigned(6, WIDTH));
        op <= OP_MUL;
        wait for 10 ns;
        assert unsigned(result) = 42 report "MUL 7*6 failed" severity failure;

        -- MUL: multiply by zero
        a <= std_logic_vector(to_unsigned(100, WIDTH));
        b <= std_logic_vector(to_unsigned(0, WIDTH));
        op <= OP_MUL;
        wait for 10 ns;
        assert zero = '1' report "MUL by zero flag wrong" severity failure;

        -- MUL: overflow (2^(WIDTH/2) * 2^(WIDTH/2) = 2^WIDTH wraps to 0)
        a <= std_logic_vector(to_unsigned(2**(WIDTH/2), WIDTH));
        b <= std_logic_vector(to_unsigned(2**(WIDTH/2), WIDTH));
        op <= OP_MUL;
        wait for 10 ns;
        assert carry = '1' report "MUL carry not set on overflow" severity failure;

        -- MUL: overflow with carry in upper bits beyond bit WIDTH
        a <= (others => '1');
        b <= std_logic_vector(to_unsigned(3, WIDTH));
        op <= OP_MUL;
        wait for 10 ns;
        assert carry = '1' report "MUL carry not set for max*3 overflow" severity failure;

        report "All ALU tests passed for WIDTH=" & integer'image(WIDTH)
            severity note;
        wait;
    end process;
end architecture;
"""
    with open("/app/tb_alu.vhd", "w") as f:
        f.write(tb)

    print("[solve] Wrote comprehensive testbench to /app/tb_alu.vhd")


def write_coverage_script():
    """Generate the multi-configuration coverage pipeline script."""
    script = r"""#!/bin/bash
# Coverage analysis pipeline for parameterized ALU
set -eo pipefail
cd /app

echo "=== NVC Coverage Pipeline ==="

# Clean previous artefacts
rm -rf work *.ncdb coverage_report

# Run coverage for each WIDTH configuration
for WIDTH in 8 16 32; do
    echo "--- WIDTH=$WIDTH ---"
    nvc -a alu.vhd tb_alu.vhd \
        -e -gWIDTH=$WIDTH --cover=all --cover-file=cov_w${WIDTH}.ncdb tb_alu \
        -r
done

# Merge all coverage databases
echo "--- Merging coverage databases ---"
nvc --cover-merge -o merged.ncdb cov_w8.ncdb cov_w16.ncdb cov_w32.ncdb

# Generate HTML report
echo "--- Generating coverage report ---"
nvc --cover-report -o coverage_report merged.ncdb

echo "=== Pipeline complete ==="
echo "Merged DB : /app/merged.ncdb"
echo "Report    : /app/coverage_report/index.html"
"""
    with open("/app/run_coverage.sh", "w") as f:
        f.write(script)

    # Make executable
    st = os.stat("/app/run_coverage.sh")
    os.chmod("/app/run_coverage.sh", st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print("[solve] Wrote /app/run_coverage.sh")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("fix", "all"):
        fix_alu()
    if cmd in ("tb", "all"):
        write_testbench()
    if cmd in ("coverage", "all"):
        write_coverage_script()
