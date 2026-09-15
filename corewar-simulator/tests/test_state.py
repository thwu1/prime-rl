
import os
import re
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, "/app")
from mars import MARS


def _write_warrior(lines):
    """Create a temporary warrior load file. Returns the path."""
    fd, path = tempfile.mkstemp(suffix=".red")
    with os.fdopen(fd, "w") as f:
        f.write(";redcode-94\n")
        for line in lines:
            f.write(line + "\n")
    return path


# ---------------------------------------------------------------------------
# Load File Parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_parse_imp(self):
        """Parse the Imp warrior: single MOV.I $0, $1."""
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior("/app/warriors/imp.red", position=0)
        cell = m.get_cell(0)
        assert cell["opcode"] == "MOV"
        assert cell["modifier"] == "I"
        assert cell["a_mode"] == "$"
        assert cell["a_number"] == 0
        assert cell["b_mode"] == "$"
        assert cell["b_number"] == 1

    def test_parse_dwarf_dat(self):
        """Parse the Dwarf's first instruction: DAT.F #0, #0."""
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        cell = m.get_cell(0)
        assert cell["opcode"] == "DAT"
        assert cell["modifier"] == "F"
        assert cell["a_mode"] == "#"
        assert cell["a_number"] == 0
        assert cell["b_mode"] == "#"
        assert cell["b_number"] == 0

    def test_parse_org_start(self):
        """ORG directive sets execution start offset — Dwarf starts at ADD."""
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        # Dwarf has ORG 1, so execution starts at pos 1 (ADD.AB #4, $-1).
        # After one step, the ADD should increment DAT's B-field by 4.
        m.step()
        cell = m.get_cell(0)
        assert cell["b_number"] == 4

    def test_negative_address_conversion(self):
        """Negative addresses are converted to modular positives by the loader."""
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        # ADD.AB #4, $-1 should have B-number = 99 (i.e. -1 mod 100)
        cell = m.get_cell(1)
        assert cell["b_number"] == 99


# ---------------------------------------------------------------------------
# MOV Instructions — all modifier variants
# ---------------------------------------------------------------------------


class TestMov:
    def test_mov_i_copies_instruction(self):
        """MOV.I copies the entire source instruction to the target."""
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior("/app/warriors/imp.red", position=0)
        m.step()  # Execute MOV.I $0, $1 at position 0
        cell = m.get_cell(1)
        assert cell["opcode"] == "MOV"
        assert cell["modifier"] == "I"
        assert cell["a_mode"] == "$"
        assert cell["a_number"] == 0
        assert cell["b_mode"] == "$"
        assert cell["b_number"] == 1

    def test_mov_a_copies_a_number(self):
        """MOV.A copies only the A-number from source to target."""
        path = _write_warrior(["MOV.A $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["a_number"] == 7
        assert cell["b_number"] == 0  # unchanged from default
        os.unlink(path)

    def test_mov_b_copies_b_number(self):
        """MOV.B copies B-number of source to B-number of target."""
        path = _write_warrior(["MOV.B $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["b_number"] == 3  # B-number of source
        assert cell["a_number"] == 0  # unchanged
        os.unlink(path)

    def test_mov_ab_copies_a_to_b(self):
        """MOV.AB copies A-number of source to B-number of target."""
        path = _write_warrior(["MOV.AB $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["b_number"] == 7  # A-number of source written to B
        assert cell["a_number"] == 0  # unchanged
        os.unlink(path)

    def test_mov_ba_copies_b_to_a(self):
        """MOV.BA copies B-number of source to A-number of target."""
        path = _write_warrior(["MOV.BA $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["a_number"] == 3  # B-number of source written to A
        assert cell["b_number"] == 0  # unchanged
        os.unlink(path)

    def test_mov_f_copies_both(self):
        """MOV.F copies both A-number and B-number."""
        path = _write_warrior(["MOV.F $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["a_number"] == 7
        assert cell["b_number"] == 3
        os.unlink(path)

    def test_mov_x_swaps(self):
        """MOV.X copies A-number to B and B-number to A (cross)."""
        path = _write_warrior(["MOV.X $1, $2", "DAT.F #7, #3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["a_number"] == 3  # B-number of source → A-number of target
        assert cell["b_number"] == 7  # A-number of source → B-number of target
        os.unlink(path)


# ---------------------------------------------------------------------------
# Arithmetic Instructions
# ---------------------------------------------------------------------------


class TestArithmetic:
    def test_add_ab(self):
        """ADD.AB adds A-number of source to B-number of target in core."""
        path = _write_warrior(["ADD.AB #5, $1", "DAT.F $0, $3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        assert cell["b_number"] == 8  # 3 + 5
        os.unlink(path)

    def test_add_f_adds_both(self):
        """ADD.F adds both A and B fields simultaneously."""
        path = _write_warrior(["ADD.F $1, $2", "DAT.F #5, #3", "DAT.F #10, #7"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(2)
        assert cell["a_number"] == 15  # 10 + 5
        assert cell["b_number"] == 10  # 7 + 3
        os.unlink(path)

    def test_sub_modular(self):
        """SUB.AB subtracts with modular wraparound."""
        path = _write_warrior(["SUB.AB #7, $1", "DAT.F $0, $3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        # (3 - 7) mod 20 = -4 mod 20 = 16
        assert cell["b_number"] == 16
        os.unlink(path)

    def test_mul_ab(self):
        """MUL.AB multiplies A-number with B-number of target."""
        path = _write_warrior(["MUL.AB #3, $1", "DAT.F $0, $5"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        assert cell["b_number"] == 15  # 5 * 3
        os.unlink(path)

    def test_div_by_zero_kills_process(self):
        """DIV by zero removes the current process."""
        path = _write_warrior(["DIV.AB #0, $1", "DAT.F $0, $7"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        assert m.get_process_count(0) == 0  # process killed
        cell = m.get_cell(1)
        assert cell["b_number"] == 7  # B-value unchanged
        os.unlink(path)

    def test_mod_ab(self):
        """MOD.AB computes A-number mod B-number of target, stores in B."""
        path = _write_warrior(["MOD.AB #3, $1", "DAT.F $0, $7"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        assert cell["b_number"] == 1  # 7 mod 3 = 1
        os.unlink(path)

    def test_mod_by_zero_kills_process(self):
        """MOD by zero removes the current process, value unchanged."""
        path = _write_warrior(["MOD.AB #0, $1", "DAT.F $0, $7"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        assert m.get_process_count(0) == 0
        cell = m.get_cell(1)
        assert cell["b_number"] == 7  # unchanged
        os.unlink(path)


# ---------------------------------------------------------------------------
# Jump Instructions
# ---------------------------------------------------------------------------


class TestJumps:
    def test_jmp(self):
        """JMP changes PC to (PC + A-pointer), skipping intervening code."""
        path = _write_warrior(
            [
                "JMP.B $3, $0",
                "DAT.F $0, $0",
                "DAT.F $0, $0",
                "NOP.F $0, $0",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        assert m.get_process_count(0) == 1  # survived (didn't hit DAT)
        m.step()
        assert m.get_process_count(0) == 1  # NOP at pos 3
        m.step()
        assert m.get_process_count(0) == 1  # NOP at pos 4
        os.unlink(path)

    def test_jmz_jump_when_zero(self):
        """JMZ.B jumps when B-number of tested instruction is zero."""
        path = _write_warrior(
            [
                "JMZ.B $3, $1",
                "DAT.F $0, $0",
                "DAT.F $0, $0",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # JMZ, B-value = 0 → jump to pos 3
        assert m.get_process_count(0) == 1
        m.step()  # NOP at pos 3
        assert m.get_process_count(0) == 1
        os.unlink(path)

    def test_jmz_no_jump_when_nonzero(self):
        """JMZ.B does NOT jump when B-number is non-zero."""
        path = _write_warrior(
            [
                "JMZ.B $3, $1",
                "DAT.F $0, $5",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # JMZ, B-value = 5 → no jump → PC = 1
        m.step()  # DAT at pos 1 → process dies
        assert m.get_process_count(0) == 0
        os.unlink(path)

    def test_jmn_jump_when_nonzero(self):
        """JMN.B jumps when B-number of tested instruction is non-zero."""
        path = _write_warrior(
            [
                "JMN.B $3, $1",
                "DAT.F $0, $5",
                "DAT.F $0, $0",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # JMN, B-value = 5 (non-zero) → jump to pos 3
        assert m.get_process_count(0) == 1
        m.step()  # NOP at pos 3
        assert m.get_process_count(0) == 1
        os.unlink(path)

    def test_jmn_no_jump_when_zero(self):
        """JMN.B does NOT jump when B-number is zero."""
        path = _write_warrior(
            [
                "JMN.B $3, $1",
                "DAT.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # JMN, B-value = 0 → no jump → PC = 1
        m.step()  # DAT at pos 1 → dies
        assert m.get_process_count(0) == 0
        os.unlink(path)

    def test_djn_decrement_and_jump(self):
        """DJN.B decrements B-number of target and jumps if result non-zero."""
        path = _write_warrior(
            [
                "DJN.B $2, $1",
                "DAT.F $0, $3",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        assert cell["b_number"] == 2  # decremented from 3
        assert m.get_process_count(0) == 1  # jumped (non-zero)
        os.unlink(path)


# ---------------------------------------------------------------------------
# Compare / Skip Instructions
# ---------------------------------------------------------------------------


class TestCompareSkip:
    def test_seq_skip_when_equal(self):
        """SEQ.B skips the next instruction when B-numbers are equal."""
        path = _write_warrior(
            [
                "SEQ.B $2, $3",
                "DAT.F $0, $0",
                "NOP.F $0, $7",
                "NOP.F $0, $7",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # SEQ → equal → PC = 2 (skip pos 1)
        assert m.get_process_count(0) == 1
        m.step()  # NOP at pos 2
        assert m.get_process_count(0) == 1
        os.unlink(path)

    def test_seq_no_skip_when_not_equal(self):
        """SEQ.B does NOT skip when B-numbers differ."""
        path = _write_warrior(
            [
                "SEQ.B $2, $3",
                "DAT.F $0, $0",
                "NOP.F $0, $7",
                "NOP.F $0, $5",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # SEQ → not equal → PC = 1
        assert m.get_process_count(0) == 1
        m.step()  # DAT at pos 1 → dies
        assert m.get_process_count(0) == 0
        os.unlink(path)

    def test_sne_skip_when_not_equal(self):
        """SNE.B skips the next instruction when B-numbers differ."""
        path = _write_warrior(
            [
                "SNE.B $2, $3",
                "DAT.F $0, $0",
                "NOP.F $0, $7",
                "NOP.F $0, $5",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # SNE, 7 != 5 → skip pos 1 → PC = 2
        assert m.get_process_count(0) == 1
        m.step()  # NOP at pos 2
        assert m.get_process_count(0) == 1
        os.unlink(path)

    def test_sne_no_skip_when_equal(self):
        """SNE.B does NOT skip when B-numbers are equal."""
        path = _write_warrior(
            [
                "SNE.B $2, $3",
                "DAT.F $0, $0",
                "NOP.F $0, $7",
                "NOP.F $0, $7",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # SNE, 7 == 7 → no skip → PC = 1
        m.step()  # DAT → dies
        assert m.get_process_count(0) == 0
        os.unlink(path)

    def test_slt_skip(self):
        """SLT.B skips when source B-number < target B-number."""
        path = _write_warrior(
            [
                "SLT.B $2, $3",
                "DAT.F $0, $0",
                "NOP.F $0, $3",
                "NOP.F $0, $7",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        # 3 < 7 → skip → PC = 2
        m.step()
        assert m.get_process_count(0) == 1
        m.step()
        assert m.get_process_count(0) == 1  # still alive
        os.unlink(path)


# ---------------------------------------------------------------------------
# NOP Instruction
# ---------------------------------------------------------------------------


class TestNop:
    def test_nop_no_effect(self):
        """NOP advances PC without modifying core or process state."""
        path = _write_warrior(
            [
                "NOP.F $0, $0",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # NOP at pos 0 → PC = 1
        assert m.get_process_count(0) == 1
        # Core unchanged (NOP doesn't modify anything)
        cell0 = m.get_cell(0)
        assert cell0["opcode"] == "NOP"
        m.step()  # NOP at pos 1 → PC = 2
        assert m.get_process_count(0) == 1
        os.unlink(path)


# ---------------------------------------------------------------------------
# Process Management
# ---------------------------------------------------------------------------


class TestProcesses:
    def test_spl_creates_process(self):
        """SPL creates a second process. Process count becomes 2."""
        path = _write_warrior(
            [
                "SPL.B $2, $0",
                "NOP.F $0, $0",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # SPL → queue PC+1=1 and target=2 → 2 processes
        assert m.get_process_count(0) == 2
        os.unlink(path)

    def test_dat_kills_process(self):
        """Executing a DAT instruction removes the process."""
        path = _write_warrior(["DAT.F $0, $0"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        assert m.get_process_count(0) == 0
        os.unlink(path)

    def test_spl_fifo_order(self):
        """SPL queues PC+1 first, then the split target (FIFO order)."""
        path = _write_warrior(
            [
                "SPL.B $3, $0",
                "MOV.AB #11, $15",
                "NOP.F $0, $0",
                "MOV.AB #17, $13",
            ]
        )
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()  # cycle 1: SPL → queue [1, 3]
        m.step()  # cycle 2: execute pos 1 → writes 11 to Core[16].B
        cell = m.get_cell(16)
        assert cell["b_number"] == 11
        m.step()  # cycle 3: execute pos 3 → writes 17 to Core[16].B
        cell = m.get_cell(16)
        assert cell["b_number"] == 17  # pos 3 executed second, overwrites
        os.unlink(path)


# ---------------------------------------------------------------------------
# Addressing Modes
# ---------------------------------------------------------------------------


class TestAddressingModes:
    def test_immediate_mode(self):
        """Immediate (#) mode uses the number as a value, not an address."""
        # ADD.AB #5, $1 — the #5 is the literal value 5, added to target B
        path = _write_warrior(["ADD.AB #5, $1", "DAT.F $0, $3"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(1)
        assert cell["b_number"] == 8  # 3 + 5
        os.unlink(path)

    def test_direct_mode(self):
        """Direct ($) mode uses the number as a relative offset."""
        # MOV.A $2, $3 — copies A-number of cell at PC+2 to A-number at PC+3
        path = _write_warrior(
            [
                "MOV.A $2, $3",
                "NOP.F $0, $0",
                "DAT.F #9, #4",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell = m.get_cell(3)
        assert cell["a_number"] == 9  # A-number from cell 2
        os.unlink(path)

    def test_b_predecrement(self):
        """B-predecrement (<) decrements the B-field before using it as indirect."""
        path = _write_warrior(
            [
                "MOV.I $2, <3",
                "NOP.F $0, $0",
                "DAT.F #0, #5",
                "DAT.F $0, $7",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        # Check pointer was decremented
        cell3 = m.get_cell(3)
        assert cell3["b_number"] == 6  # decremented from 7
        # Check source was copied to the indirect target
        cell9 = m.get_cell(9)
        assert cell9["opcode"] == "DAT"
        assert cell9["a_number"] == 0
        assert cell9["b_number"] == 5
        os.unlink(path)

    def test_b_postincrement(self):
        """B-postincrement (>) uses B-field for indirect THEN increments it."""
        path = _write_warrior(
            [
                "MOV.I $2, >3",
                "NOP.F $0, $0",
                "DAT.F #0, #5",
                "DAT.F $0, $7",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        # Check pointer was incremented AFTER use
        cell3 = m.get_cell(3)
        assert cell3["b_number"] == 8  # incremented from 7
        # Check source was copied to pos 10 (using original B=7)
        cell10 = m.get_cell(10)
        assert cell10["opcode"] == "DAT"
        assert cell10["a_number"] == 0
        assert cell10["b_number"] == 5
        os.unlink(path)

    def test_b_indirect(self):
        """B-indirect (@) uses B-field as secondary offset."""
        path = _write_warrior(
            [
                "MOV.I $1, @2",
                "DAT.F #0, #5",
                "DAT.F $0, $4",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell6 = m.get_cell(6)
        assert cell6["opcode"] == "DAT"
        assert cell6["b_number"] == 5
        os.unlink(path)

    def test_a_indirect(self):
        """A-indirect (*) uses A-field as secondary offset."""
        path = _write_warrior(
            [
                "MOV.I *1, $5",
                "DAT.F $3, $0",
                "NOP.F $0, $0",
                "NOP.F $0, $0",
                "DAT.F #9, #8",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        cell5 = m.get_cell(5)
        assert cell5["opcode"] == "DAT"
        assert cell5["a_number"] == 9
        assert cell5["b_number"] == 8
        os.unlink(path)

    def test_a_predecrement(self):
        """A-predecrement ({) decrements A-field of pointer before using as indirect."""
        # MOV.I {2, $5 at pos 0.
        # Pos 2 = DAT $4, $0 (A-field = 4, used for indirect).
        # Predecrement: pos 2 A-field → 4-1 = 3.
        # Indirect source: (2 + 3) = 5 from PC(0) → read from pos 5.
        path = _write_warrior(
            [
                "MOV.I {2, $6",
                "NOP.F $0, $0",
                "DAT.F $4, $0",
                "NOP.F $0, $0",
                "NOP.F $0, $0",
                "DAT.F #11, #12",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        # A-field of pointer cell was decremented
        cell2 = m.get_cell(2)
        assert cell2["a_number"] == 3  # decremented from 4
        # Source was read using decremented pointer: pos 2+3=5
        cell6 = m.get_cell(6)
        assert cell6["opcode"] == "DAT"
        assert cell6["a_number"] == 11
        assert cell6["b_number"] == 12
        os.unlink(path)

    def test_a_postincrement(self):
        """A-postincrement (}) uses A-field for indirect THEN increments it."""
        # MOV.I }2, $6 at pos 0.
        # Pos 2 = DAT $3, $0 (A-field = 3, used for indirect).
        # Use A-field: indirect source = (2 + 3) = 5 from PC(0).
        # THEN increment: pos 2 A-field → 3+1 = 4.
        path = _write_warrior(
            [
                "MOV.I }2, $6",
                "NOP.F $0, $0",
                "DAT.F $3, $0",
                "NOP.F $0, $0",
                "NOP.F $0, $0",
                "DAT.F #11, #12",
                "NOP.F $0, $0",
            ]
        )
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        m.step()
        # A-field of pointer cell was incremented AFTER use
        cell2 = m.get_cell(2)
        assert cell2["a_number"] == 4  # incremented from 3
        # Source was read using original A-field=3: pos 2+3=5
        cell6 = m.get_cell(6)
        assert cell6["opcode"] == "DAT"
        assert cell6["a_number"] == 11
        assert cell6["b_number"] == 12
        os.unlink(path)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_imp_march(self):
        """The Imp (MOV.I $0, $1) fills core forward one cell per cycle."""
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior("/app/warriors/imp.red", position=0)
        for _ in range(10):
            m.step()
        for i in range(11):
            cell = m.get_cell(i)
            assert cell["opcode"] == "MOV", f"pos {i} opcode"
            assert cell["modifier"] == "I", f"pos {i} modifier"
            assert cell["a_number"] == 0, f"pos {i} a_number"
            assert cell["b_number"] == 1, f"pos {i} b_number"

    def test_imp_vs_imp_tie(self):
        """Two Imps at different positions result in a tie."""
        m = MARS(core_size=100, max_processes=100, max_cycles=200)
        m.load_warrior("/app/warriors/imp.red", position=0)
        m.load_warrior("/app/warriors/imp.red", position=50)
        result = m.run()
        assert result["winner"] is None  # tie
        assert result["cycles"] == 200  # ran to max_cycles

    def test_battle_winner(self):
        """A warrior that writes DAT over the opponent's code wins."""
        killer_path = _write_warrior(
            [
                "MOV.I $2, $50",
                "JMP.B $-1, $0",
                "DAT.F $0, $0",
            ]
        )
        m = MARS(core_size=100, max_processes=100, max_cycles=200)
        m.load_warrior(killer_path, position=0)
        m.load_warrior("/app/warriors/target.red", position=50)
        result = m.run()
        assert result["winner"] == 0  # killer wins
        assert result["cycles"] == 1  # kills in first cycle
        os.unlink(killer_path)

    def test_dwarf_bombs(self):
        """The Dwarf drops DAT bombs every 4 positions."""
        m = MARS(core_size=100, max_processes=100, max_cycles=100)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        # Run 3 cycles (ADD, MOV, JMP) = one bombing pass.
        for _ in range(3):
            m.step()
        cell = m.get_cell(4)
        assert cell["opcode"] == "DAT"

    def test_default_modifier_assignment(self):
        """Without explicit modifier, correct defaults are assigned."""
        # MOV $1, $2 (both non-#) should default to .I
        # ADD #3, $2 (# A-mode) should default to .AB
        path = _write_warrior(["MOV $1, $2", "ADD #3, $2", "DAT $0, $0"])
        m = MARS(core_size=20, max_processes=20, max_cycles=100)
        m.load_warrior(path, position=0)
        cell0 = m.get_cell(0)
        assert cell0["modifier"] == "I"  # MOV non-# non-# → .I
        cell1 = m.get_cell(1)
        assert cell1["modifier"] == "AB"  # ADD # any → .AB
        os.unlink(path)


# ---------------------------------------------------------------------------
# pMARS Cross-Validation
# ---------------------------------------------------------------------------


def _run_pmars_battle(w1_path, w2_path, core_size=100, max_cycles=200,
                      max_procs=100, w2_pos=50, rounds=1):
    """Run a pMARS battle and return (w1_wins, w1_losses, ties)."""
    cmd = [
        "/usr/local/bin/pmars",
        "-b", "-r", str(rounds),
        "-s", str(core_size), "-c", str(max_cycles),
        "-p", str(max_procs), "-l", "10",
        "-F", str(w2_pos),
        w1_path, w2_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    output = result.stdout + "\n" + result.stderr
    for line in output.split("\n"):
        if line.strip().startswith("Results:"):
            parts = line.strip().split()
            return int(parts[1]), int(parts[2]), int(parts[3])
    raise ValueError(
        f"Could not parse pMARS output.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


class TestPmarsValidation:
    """Cross-validate Python MARS against the pMARS reference implementation."""

    def test_pmars_imp_vs_target(self):
        """Imp vs Target: Python MARS winner matches pMARS."""
        w1_wins, w1_losses, ties = _run_pmars_battle(
            "/app/warriors/imp.red", "/app/warriors/target.red",
            core_size=100, max_cycles=200, w2_pos=50,
        )
        m = MARS(core_size=100, max_processes=100, max_cycles=200)
        m.load_warrior("/app/warriors/imp.red", position=0)
        m.load_warrior("/app/warriors/target.red", position=50)
        py_result = m.run()

        if w1_wins == 1:
            assert py_result["winner"] == 0, "Python MARS should agree: warrior 0 (imp) wins"
        elif w1_losses == 1:
            assert py_result["winner"] == 1, "Python MARS should agree: warrior 1 (target) wins"
        else:
            assert py_result["winner"] is None, "Python MARS should agree: tie"

    def test_pmars_dwarf_vs_target(self):
        """Dwarf vs Target: Python MARS winner matches pMARS."""
        w1_wins, w1_losses, ties = _run_pmars_battle(
            "/app/warriors/dwarf.red", "/app/warriors/target.red",
            core_size=100, max_cycles=200, w2_pos=50,
        )
        m = MARS(core_size=100, max_processes=100, max_cycles=200)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        m.load_warrior("/app/warriors/target.red", position=50)
        py_result = m.run()

        if w1_wins == 1:
            assert py_result["winner"] == 0, "Python MARS should agree: dwarf wins"
        elif w1_losses == 1:
            assert py_result["winner"] == 1, "Python MARS should agree: target wins"
        else:
            assert py_result["winner"] is None, "Python MARS should agree: tie"

    def test_pmars_imp_vs_imp(self):
        """Imp vs Imp: should tie in both implementations."""
        w1_wins, w1_losses, ties = _run_pmars_battle(
            "/app/warriors/imp.red", "/app/warriors/imp.red",
            core_size=100, max_cycles=200, w2_pos=50,
        )
        m = MARS(core_size=100, max_processes=100, max_cycles=200)
        m.load_warrior("/app/warriors/imp.red", position=0)
        m.load_warrior("/app/warriors/imp.red", position=50)
        py_result = m.run()

        assert ties == 1 and w1_wins == 0, "pMARS: imp vs imp should be a tie"
        assert py_result["winner"] is None, "Python MARS: imp vs imp should be a tie"

    def test_pmars_dwarf_vs_imp(self):
        """Dwarf vs Imp at position 50: outcome matches pMARS."""
        w1_wins, w1_losses, ties = _run_pmars_battle(
            "/app/warriors/dwarf.red", "/app/warriors/imp.red",
            core_size=8000, max_cycles=80000, max_procs=8000, w2_pos=4000,
        )
        m = MARS(core_size=8000, max_processes=8000, max_cycles=80000)
        m.load_warrior("/app/warriors/dwarf.red", position=0)
        m.load_warrior("/app/warriors/imp.red", position=4000)
        py_result = m.run()

        if w1_wins == 1:
            assert py_result["winner"] == 0
        elif w1_losses == 1:
            assert py_result["winner"] == 1
        else:
            assert py_result["winner"] is None
