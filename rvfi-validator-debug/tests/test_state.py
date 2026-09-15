
"""Tests for the RISC-V RVFI trace validator (RV32IM).

Each test constructs RVFI trace records with known-correct (or known-incorrect)
signal values and verifies that the validator produces the expected result.
Covers all RV32I base instructions and RV32M multiply/divide extension.
"""

import sys
import pytest

sys.path.insert(0, '/app')

from rvfi_validator.decoder import decode, sign_extend, mask32
from rvfi_validator.spec_checker import check_instruction, Violation
from rvfi_validator.consistency import ConsistencyChecker
from rvfi_validator import validate_trace


# ============================================================================
# Instruction encoding helpers
# ============================================================================

def encode_r(funct7, rs2, rs1, funct3, rd):
    """Encode an R-type instruction."""
    return ((funct7 & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | \
           ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | \
           ((rd & 0x1F) << 7) | 0x33


def encode_m(funct3, rs2, rs1, rd):
    """Encode an M-extension instruction (R-type with funct7=0x01)."""
    return encode_r(0x01, rs2, rs1, funct3, rd)


def encode_i(imm12, rs1, funct3, rd, opcode):
    """Encode an I-type instruction."""
    return ((imm12 & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) | \
           ((funct3 & 0x7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def encode_s(imm12, rs2, rs1, funct3):
    """Encode an S-type instruction."""
    imm_11_5 = (imm12 >> 5) & 0x7F
    imm_4_0 = imm12 & 0x1F
    return (imm_11_5 << 25) | ((rs2 & 0x1F) << 20) | \
           ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | \
           (imm_4_0 << 7) | 0x23


def encode_b(imm, rs2, rs1, funct3):
    """Encode a B-type instruction. imm is the full signed offset."""
    u = imm & 0x1FFF  # 13-bit mask
    imm_12 = (u >> 12) & 1
    imm_11 = (u >> 11) & 1
    imm_10_5 = (u >> 5) & 0x3F
    imm_4_1 = (u >> 1) & 0xF
    return (imm_12 << 31) | (imm_10_5 << 25) | ((rs2 & 0x1F) << 20) | \
           ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | \
           (imm_4_1 << 8) | (imm_11 << 7) | 0x63


def encode_u(imm, rd, opcode):
    """Encode a U-type instruction. imm has lower 12 bits zero."""
    return (imm & 0xFFFFF000) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def encode_j(imm, rd):
    """Encode a J-type (JAL) instruction."""
    u = imm & 0x1FFFFF  # 21-bit mask
    imm_20 = (u >> 20) & 1
    imm_10_1 = (u >> 1) & 0x3FF
    imm_11 = (u >> 11) & 1
    imm_19_12 = (u >> 12) & 0xFF
    return (imm_20 << 31) | (imm_10_1 << 21) | (imm_11 << 20) | \
           (imm_19_12 << 12) | ((rd & 0x1F) << 7) | 0x6F


def make_rvfi(**kwargs):
    """Create an RVFI record with sensible defaults."""
    defaults = {
        'insn': 0x00000033,  # ADD x0, x0, x0
        'rs1_addr': 0, 'rs1_rdata': 0,
        'rs2_addr': 0, 'rs2_rdata': 0,
        'rd_addr': 0, 'rd_wdata': 0,
        'pc_rdata': 0, 'pc_wdata': 4,
        'mem_addr': 0, 'mem_rmask': 0, 'mem_wmask': 0,
        'mem_rdata': 0, 'mem_wdata': 0,
        'trap': 0, 'halt': 0, 'intr': 0,
    }
    defaults.update(kwargs)
    return defaults


# ============================================================================
# Tests for basic ALU operations (R-type)
# ============================================================================

class TestBasicALU:
    def test_add(self):
        """ADD x3, x1, x2: 5 + 3 = 8."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=8,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sub(self):
        """SUB x3, x1, x2: 10 - 3 = 7."""
        rvfi = make_rvfi(
            insn=encode_r(0x20, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=10,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=7,
            pc_rdata=0x100, pc_wdata=0x104,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sll(self):
        """SLL x3, x1, x2: 1 << 4 = 16."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 1, 3),
            rs1_addr=1, rs1_rdata=1,
            rs2_addr=2, rs2_rdata=4,
            rd_addr=3, rd_wdata=16,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_srl(self):
        """SRL x3, x1, x2: 0x80000000 >> 4 = 0x08000000 (logical)."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 5, 3),
            rs1_addr=1, rs1_rdata=0x80000000,
            rs2_addr=2, rs2_rdata=4,
            rd_addr=3, rd_wdata=0x08000000,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sra_negative(self):
        """SRA x3, x1, x2: arithmetic shift of 0x80000000 >> 4 = 0xF8000000.

        Exercises Bug 3: SRA must use arithmetic (sign-extending) shift,
        not logical shift.
        """
        rvfi = make_rvfi(
            insn=encode_r(0x20, 2, 1, 5, 3),
            rs1_addr=1, rs1_rdata=0x80000000,
            rs2_addr=2, rs2_rdata=4,
            rd_addr=3, rd_wdata=0xF8000000,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"SRA violations: {violations}"

    def test_sra_positive(self):
        """SRA of positive value should behave like SRL."""
        rvfi = make_rvfi(
            insn=encode_r(0x20, 2, 1, 5, 3),
            rs1_addr=1, rs1_rdata=0x40000000,
            rs2_addr=2, rs2_rdata=4,
            rd_addr=3, rd_wdata=0x04000000,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_slt_signed(self):
        """SLT: signed(-1) < signed(1) -> 1."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 2, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,  # -1
            rs2_addr=2, rs2_rdata=1,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sltu_unsigned(self):
        """SLTU: unsigned(1) < unsigned(0xFFFFFFFF) -> 1."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 3, 3),
            rs1_addr=1, rs1_rdata=1,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_and_or_xor(self):
        """AND, OR, XOR basic checks."""
        for funct3, op in [(7, lambda a, b: a & b),
                           (6, lambda a, b: a | b),
                           (4, lambda a, b: a ^ b)]:
            a, b = 0xF0F0F0F0, 0xFF00FF00
            rvfi = make_rvfi(
                insn=encode_r(0x00, 2, 1, funct3, 3),
                rs1_addr=1, rs1_rdata=a,
                rs2_addr=2, rs2_rdata=b,
                rd_addr=3, rd_wdata=op(a, b),
                pc_rdata=0, pc_wdata=4,
            )
            violations = check_instruction(rvfi)
            assert len(violations) == 0, f"funct3={funct3} violations: {violations}"


# ============================================================================
# Tests for I-type ALU operations
# ============================================================================

class TestImmALU:
    def test_addi(self):
        """ADDI x3, x1, -1: 10 + (-1) = 9."""
        rvfi = make_rvfi(
            insn=encode_i(0xFFF, 1, 0, 3, 0x13),  # imm = -1
            rs1_addr=1, rs1_rdata=10,
            rd_addr=3, rd_wdata=9,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_srai_negative(self):
        """SRAI x3, x1, 4: arithmetic shift of 0x80000000 -> 0xF8000000.

        Exercises Bug 3 (same as SRA but I-type encoding).
        """
        # SRAI: funct7=0x20, shamt=4, funct3=5, opcode=0x13
        imm_field = (0x20 << 5) | 4  # 0x404
        rvfi = make_rvfi(
            insn=encode_i(imm_field, 1, 5, 3, 0x13),
            rs1_addr=1, rs1_rdata=0x80000000,
            rd_addr=3, rd_wdata=0xF8000000,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"SRAI violations: {violations}"

    def test_srli(self):
        """SRLI x3, x1, 4: logical shift of 0x80000000 -> 0x08000000."""
        imm_field = (0x00 << 5) | 4  # 0x004
        rvfi = make_rvfi(
            insn=encode_i(imm_field, 1, 5, 3, 0x13),
            rs1_addr=1, rs1_rdata=0x80000000,
            rd_addr=3, rd_wdata=0x08000000,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_slti(self):
        """SLTI x3, x1, -1: signed(5) < signed(-1) -> 0."""
        rvfi = make_rvfi(
            insn=encode_i(0xFFF, 1, 2, 3, 0x13),  # imm = -1
            rs1_addr=1, rs1_rdata=5,
            rd_addr=3, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sltiu(self):
        """SLTIU x3, x1, -1: unsigned(5) < unsigned(0xFFFFFFFF) -> 1."""
        rvfi = make_rvfi(
            insn=encode_i(0xFFF, 1, 3, 3, 0x13),
            rs1_addr=1, rs1_rdata=5,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0


# ============================================================================
# Tests for upper-immediate instructions (LUI, AUIPC)
# ============================================================================

class TestUpper:
    def test_lui(self):
        """LUI x1, 0xDEADB: rd = 0xDEADB000."""
        rvfi = make_rvfi(
            insn=encode_u(0xDEADB000, 1, 0x37),
            rd_addr=1, rd_wdata=0xDEADB000,
            pc_rdata=0x100, pc_wdata=0x104,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_auipc(self):
        """AUIPC x1, 0x12345: rd = pc + 0x12345000.

        Exercises Bug 7: AUIPC handler must be implemented.
        """
        rvfi = make_rvfi(
            insn=encode_u(0x12345000, 1, 0x17),
            rd_addr=1, rd_wdata=mask32(0x200 + 0x12345000),
            pc_rdata=0x200, pc_wdata=0x204,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"AUIPC violations: {violations}"


# ============================================================================
# Tests for branch instructions
# ============================================================================

class TestBranch:
    def test_beq_taken_small(self):
        """BEQ x0, x0, +8: always taken, small positive offset."""
        rvfi = make_rvfi(
            insn=encode_b(8, 0, 0, 0),
            rs1_addr=0, rs1_rdata=0,
            rs2_addr=0, rs2_rdata=0,
            pc_rdata=0x100, pc_wdata=0x108,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_beq_not_taken(self):
        """BEQ x1, x2, +8: not taken when rs1 != rs2."""
        rvfi = make_rvfi(
            insn=encode_b(8, 2, 1, 0),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            pc_rdata=0x100, pc_wdata=0x104,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_beq_forward_large_offset(self):
        """BEQ x0, x0, +2048: forward branch with offset requiring 13-bit sign ext.

        Exercises Bug 1: B-type immediate must be sign-extended from 13 bits.
        With the bug, +2048 is misinterpreted as -2048.
        """
        rvfi = make_rvfi(
            insn=encode_b(2048, 0, 0, 0),
            rs1_addr=0, rs1_rdata=0,
            rs2_addr=0, rs2_rdata=0,
            pc_rdata=0x1000, pc_wdata=mask32(0x1000 + 2048),
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"BEQ forward violations: {violations}"

    def test_bne_backward(self):
        """BNE x1, x2, -8: taken backward branch."""
        imm = (-8) & 0x1FFF  # 13-bit
        rvfi = make_rvfi(
            insn=encode_b(imm, 2, 1, 1),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            pc_rdata=0x200, pc_wdata=mask32(0x200 - 8),
        )
        assert len(check_instruction(rvfi)) == 0

    def test_blt_signed(self):
        """BLT: signed(-1) < signed(0) -> taken."""
        rvfi = make_rvfi(
            insn=encode_b(16, 2, 1, 4),  # BLT
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,  # -1
            rs2_addr=2, rs2_rdata=0,
            pc_rdata=0x100, pc_wdata=0x110,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_bgeu(self):
        """BGEU: unsigned(0xFFFFFFFF) >= unsigned(1) -> taken."""
        rvfi = make_rvfi(
            insn=encode_b(16, 2, 1, 7),  # BGEU
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=1,
            pc_rdata=0x100, pc_wdata=0x110,
        )
        assert len(check_instruction(rvfi)) == 0


# ============================================================================
# Tests for jump instructions
# ============================================================================

class TestJump:
    def test_jal(self):
        """JAL x1, +8: jump and link."""
        rvfi = make_rvfi(
            insn=encode_j(8, 1),
            rd_addr=1, rd_wdata=0x304,  # link = pc + 4
            pc_rdata=0x300, pc_wdata=0x308,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_jalr_even_target(self):
        """JALR x1, 0(x2): target is already even."""
        rvfi = make_rvfi(
            insn=encode_i(0, 2, 0, 1, 0x67),
            rs1_addr=2, rs1_rdata=0x100,
            rd_addr=1, rd_wdata=0x204,
            pc_rdata=0x200, pc_wdata=0x100,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_jalr_odd_target(self):
        """JALR x1, 0(x2) with x2=0x101: LSB must be cleared -> target=0x100.

        Exercises Bug 4: JALR target = (rs1 + imm) & ~1.
        """
        rvfi = make_rvfi(
            insn=encode_i(0, 2, 0, 1, 0x67),
            rs1_addr=2, rs1_rdata=0x101,
            rd_addr=1, rd_wdata=0x204,
            pc_rdata=0x200, pc_wdata=0x100,  # 0x101 & ~1 = 0x100
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"JALR odd target violations: {violations}"


# ============================================================================
# Tests for load instructions
# ============================================================================

class TestLoad:
    def test_lw(self):
        """LW x3, 0(x1): load word."""
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 2, 3, 0x03),
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=0xDEADBEEF,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0xF, mem_rdata=0xDEADBEEF,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_lb_sign_extend(self):
        """LB x3, 0(x1): byte 0x80 sign-extends to 0xFFFFFF80."""
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 0, 3, 0x03),
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=0xFFFFFF80,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0x1, mem_rdata=0x80,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_lbu_zero_extend(self):
        """LBU x3, 0(x1): byte 0x80 zero-extends to 0x00000080."""
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 4, 3, 0x03),
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=0x80,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0x1, mem_rdata=0x80,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_lh_negative_value(self):
        """LH x3, 0(x1): halfword 0x8001 sign-extends to 0xFFFF8001.

        Exercises Bug 5: LH must sign-extend, not zero-extend.
        """
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 1, 3, 0x03),  # LH
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=0xFFFF8001,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0x3, mem_rdata=0x8001,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"LH sign-extend violations: {violations}"

    def test_lhu_zero_extend(self):
        """LHU x3, 0(x1): halfword 0x8001 zero-extends to 0x00008001."""
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 5, 3, 0x03),  # LHU
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=0x8001,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0x3, mem_rdata=0x8001,
        )
        assert len(check_instruction(rvfi)) == 0


# ============================================================================
# Tests for store instructions
# ============================================================================

class TestStore:
    def test_sw(self):
        """SW x2, 0(x1): store word."""
        rvfi = make_rvfi(
            insn=encode_s(0, 2, 1, 2),
            rs1_addr=1, rs1_rdata=0x2000,
            rs2_addr=2, rs2_rdata=0xCAFEBABE,
            rd_addr=0, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x2000, mem_wmask=0xF, mem_wdata=0xCAFEBABE,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sw_negative_offset(self):
        """SW x2, -8(x1): S-type immediate must be sign-extended.

        Exercises Bug 2: S-type immediate missing sign extension.
        """
        imm = (-8) & 0xFFF  # 12-bit representation of -8
        rvfi = make_rvfi(
            insn=encode_s(imm, 2, 1, 2),
            rs1_addr=1, rs1_rdata=0x100,
            rs2_addr=2, rs2_rdata=0xDEADBEEF,
            rd_addr=0, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
            mem_addr=mask32(0x100 - 8),  # 0xF8
            mem_wmask=0xF, mem_wdata=0xDEADBEEF,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"SW negative offset violations: {violations}"

    def test_sh(self):
        """SH x2, 0(x1): store halfword, wmask=0x3."""
        rvfi = make_rvfi(
            insn=encode_s(0, 2, 1, 1),
            rs1_addr=1, rs1_rdata=0x2000,
            rs2_addr=2, rs2_rdata=0x1234,
            rd_addr=0, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x2000, mem_wmask=0x3, mem_wdata=0x1234,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_sb_write_mask(self):
        """SB x2, 0(x1): byte store must use wmask=0x1.

        Exercises Bug 6: SB write mask must be 0x1, not 0x3.
        """
        rvfi = make_rvfi(
            insn=encode_s(0, 2, 1, 0),  # SB
            rs1_addr=1, rs1_rdata=0x2000,
            rs2_addr=2, rs2_rdata=0x42,
            rd_addr=0, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x2000, mem_wmask=0x1, mem_wdata=0x42,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"SB write mask violations: {violations}"


# ============================================================================
# Tests for cross-instruction consistency
# ============================================================================

class TestConsistency:
    def test_register_shadow_basic(self):
        """Register shadow: write then read should be consistent."""
        checker = ConsistencyChecker()

        # Instruction 1: writes x3 = 8
        rvfi1 = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=8,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(checker.check_and_update(rvfi1)) == 0

        # Instruction 2: reads x3 (should be 8)
        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 3, 0, 4),
            rs1_addr=3, rs1_rdata=8,  # Matches shadow
            rs2_addr=0, rs2_rdata=0,
            rd_addr=4, rd_wdata=8,
            pc_rdata=4, pc_wdata=8,
        )
        assert len(checker.check_and_update(rvfi2)) == 0

    def test_pc_continuity_normal(self):
        """PC should flow continuously for sequential instructions."""
        checker = ConsistencyChecker()

        rvfi1 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x100, pc_wdata=0x104,
        )
        assert len(checker.check_and_update(rvfi1)) == 0

        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x104, pc_wdata=0x108,
        )
        assert len(checker.check_and_update(rvfi2)) == 0

    def test_interrupt_pc_discontinuity(self):
        """PC discontinuity is allowed when intr=1 (interrupt handler).

        Exercises Bug 8: consistency checker must skip PC check when intr=1.
        """
        checker = ConsistencyChecker()

        # Normal instruction
        rvfi1 = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=8,
            pc_rdata=0x100, pc_wdata=0x104,
        )
        assert len(checker.check_and_update(rvfi1)) == 0

        # Interrupt handler: pc_rdata doesn't match previous pc_wdata
        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x80000000, pc_wdata=0x80000004,
            intr=1,
        )
        violations = checker.check_and_update(rvfi2)
        assert len(violations) == 0, f"Interrupt PC violations: {violations}"

    def test_trap_disables_pc_tracking(self):
        """After a trap, shadow PC becomes invalid."""
        checker = ConsistencyChecker()

        # Trapping instruction
        rvfi1 = make_rvfi(
            insn=0x00000000,  # Illegal instruction
            trap=1,
            pc_rdata=0x100, pc_wdata=0x80000000,
        )
        checker.check_and_update(rvfi1)

        # Next instruction at trap handler: no PC mismatch because shadow is invalid
        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x80000000, pc_wdata=0x80000004,
            intr=1,
        )
        violations = checker.check_and_update(rvfi2)
        assert len(violations) == 0


# ============================================================================
# Tests for full trace validation
# ============================================================================

class TestFullTrace:
    def test_simple_program(self):
        """Validate a short correct program trace."""
        trace = [
            # ADDI x1, x0, 5
            make_rvfi(
                insn=encode_i(5, 0, 0, 1, 0x13),
                rs1_addr=0, rs1_rdata=0,
                rd_addr=1, rd_wdata=5,
                pc_rdata=0, pc_wdata=4,
            ),
            # ADDI x2, x0, 3
            make_rvfi(
                insn=encode_i(3, 0, 0, 2, 0x13),
                rs1_addr=0, rs1_rdata=0,
                rd_addr=2, rd_wdata=3,
                pc_rdata=4, pc_wdata=8,
            ),
            # ADD x3, x1, x2  -> 5 + 3 = 8
            make_rvfi(
                insn=encode_r(0x00, 2, 1, 0, 3),
                rs1_addr=1, rs1_rdata=5,
                rs2_addr=2, rs2_rdata=3,
                rd_addr=3, rd_wdata=8,
                pc_rdata=8, pc_wdata=12,
            ),
        ]
        results = validate_trace(trace)
        assert len(results) == 0, f"Trace violations: {results}"


# ============================================================================
# M-extension: Multiply instructions
# ============================================================================

class TestMExtMul:
    """Tests for M-extension multiply instructions (MUL, MULH, MULHU, MULHSU)."""

    def test_mul_basic(self):
        """MUL: 6 x 7 = 42."""
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=6,
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=42,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mul_large_unsigned(self):
        """MUL: 0xFFFFFFFF x 0xFFFFFFFF -> lower 32 bits = 0x00000001."""
        # (2^32-1)^2 = 2^64 - 2^33 + 1, lower 32 = 1
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mul_negative(self):
        """MUL: (-7) x 7 = -49 -> lower 32 = 0xFFFFFFCF."""
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFF9,  # -7
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=mask32(-49),  # 0xFFFFFFCF
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mulh_positive(self):
        """MULH: 0x10000 x 0x10000 -> upper 32 of 0x100000000 = 1."""
        rvfi = make_rvfi(
            insn=encode_m(1, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0x10000,
            rs2_addr=2, rs2_rdata=0x10000,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mulh_negative(self):
        """MULH: (-7) x 7 = -49 -> upper 32 = 0xFFFFFFFF."""
        rvfi = make_rvfi(
            insn=encode_m(1, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFF9,  # -7
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=0xFFFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mulh_neg_neg(self):
        """MULH: (-1) x (-1) = 1 -> upper 32 = 0."""
        rvfi = make_rvfi(
            insn=encode_m(1, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mulhu_large(self):
        """MULHU: 0xFFFFFFFF x 0xFFFFFFFF -> upper 32 = 0xFFFFFFFE."""
        # (2^32-1)^2 = 0xFFFFFFFE_00000001
        rvfi = make_rvfi(
            insn=encode_m(3, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0xFFFFFFFE,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_mulhsu_neg_unsigned(self):
        """MULHSU: signed(-1) x unsigned(0xFFFFFFFF).
        Product = -4294967295, 64-bit = 0xFFFFFFFF_00000001, upper = 0xFFFFFFFF.
        """
        rvfi = make_rvfi(
            insn=encode_m(2, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,  # signed: -1
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,  # unsigned: 4294967295
            rd_addr=3, rd_wdata=0xFFFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"MULHSU violations: {violations}"

    def test_mulhsu_pos_unsigned(self):
        """MULHSU: signed(2) x unsigned(0x80000000).
        Product = 2 * 2147483648 = 4294967296 = 0x1_00000000, upper = 1.
        """
        rvfi = make_rvfi(
            insn=encode_m(2, 2, 1, 3),
            rs1_addr=1, rs1_rdata=2,
            rs2_addr=2, rs2_rdata=0x80000000,
            rd_addr=3, rd_wdata=1,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"MULHSU pos violations: {violations}"

    def test_mulhsu_neg_large(self):
        """MULHSU: signed(-2) x unsigned(0x80000000).
        Product = -4294967296 = 0xFFFFFFFF_00000000, upper = 0xFFFFFFFF.
        """
        rvfi = make_rvfi(
            insn=encode_m(2, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFE,  # signed: -2
            rs2_addr=2, rs2_rdata=0x80000000,
            rd_addr=3, rd_wdata=0xFFFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"MULHSU neg large violations: {violations}"

    def test_mul_zero(self):
        """MUL: anything x 0 = 0."""
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xDEADBEEF,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0


# ============================================================================
# M-extension: Division/remainder instructions
# ============================================================================

class TestMExtDiv:
    """Tests for M-extension divide/remainder instructions."""

    def test_div_basic(self):
        """DIV: 42 / 7 = 6."""
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=6,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_div_negative(self):
        """DIV: -13 / 5 = -2 (truncated toward zero)."""
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFF3,  # -13
            rs2_addr=2, rs2_rdata=5,
            rd_addr=3, rd_wdata=mask32(-2),  # 0xFFFFFFFE
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"DIV neg violations: {violations}"

    def test_div_by_zero(self):
        """DIV: 42 / 0 = 0xFFFFFFFF (defined, no trap)."""
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0xFFFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"DIV zero violations: {violations}"

    def test_div_overflow(self):
        """DIV: -2^31 / -1 = -2^31 (overflow, defined result)."""
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0x80000000,  # -2^31
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,  # -1
            rd_addr=3, rd_wdata=0x80000000,     # -2^31
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"DIV overflow violations: {violations}"

    def test_divu_basic(self):
        """DIVU: 42 / 7 = 6."""
        rvfi = make_rvfi(
            insn=encode_m(5, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=6,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_divu_by_zero(self):
        """DIVU: 42 / 0 = 0xFFFFFFFF."""
        rvfi = make_rvfi(
            insn=encode_m(5, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0xFFFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"DIVU zero violations: {violations}"

    def test_divu_large(self):
        """DIVU: 0xFFFFFFFF / 2 = 0x7FFFFFFF."""
        rvfi = make_rvfi(
            insn=encode_m(5, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=2,
            rd_addr=3, rd_wdata=0x7FFFFFFF,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_rem_negative(self):
        """REM: -13 % 5 = -3 (sign matches dividend)."""
        rvfi = make_rvfi(
            insn=encode_m(6, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFF3,  # -13
            rs2_addr=2, rs2_rdata=5,
            rd_addr=3, rd_wdata=mask32(-3),  # 0xFFFFFFFD
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"REM neg violations: {violations}"

    def test_rem_by_zero(self):
        """REM: 42 % 0 = 42 (return dividend)."""
        rvfi = make_rvfi(
            insn=encode_m(6, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=42,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"REM zero violations: {violations}"

    def test_rem_overflow(self):
        """REM: -2^31 % -1 = 0 (overflow case)."""
        rvfi = make_rvfi(
            insn=encode_m(6, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0x80000000,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"REM overflow violations: {violations}"

    def test_remu_basic(self):
        """REMU: 42 % 5 = 2."""
        rvfi = make_rvfi(
            insn=encode_m(7, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=5,
            rd_addr=3, rd_wdata=2,
            pc_rdata=0, pc_wdata=4,
        )
        assert len(check_instruction(rvfi)) == 0

    def test_remu_by_zero(self):
        """REMU: 42 % 0 = 42 (return dividend)."""
        rvfi = make_rvfi(
            insn=encode_m(7, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=42,
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert len(violations) == 0, f"REMU zero violations: {violations}"


# ============================================================================
# Negative tests: verify the validator DETECTS violations
# ============================================================================

class TestViolationDetection:
    """Ensure the validator correctly identifies real errors in traces.

    These tests must pass regardless of bug fixes to prevent the agent
    from disabling checks as a "fix".
    """

    def test_wrong_add_result(self):
        """ADD with wrong result must be detected."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=9,  # Wrong! 5+3=8
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong ADD result"

    def test_wrong_pc_next(self):
        """Wrong next PC must be detected."""
        rvfi = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=8,
            pc_rdata=0, pc_wdata=8,  # Wrong! Should be 4
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'pc_wdata' for v in violations), \
            "Validator must detect wrong next PC"

    def test_wrong_store_data(self):
        """Store with wrong wdata must be detected."""
        rvfi = make_rvfi(
            insn=encode_s(0, 2, 1, 2),  # SW
            rs1_addr=1, rs1_rdata=0x2000,
            rs2_addr=2, rs2_rdata=0xDEADBEEF,
            rd_addr=0, rd_wdata=0,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x2000, mem_wmask=0xF,
            mem_wdata=0xBAADF00D,  # Wrong!
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'mem_wdata' for v in violations), \
            "Validator must detect wrong store data"

    def test_register_consistency_violation(self):
        """Register read inconsistency must be detected."""
        checker = ConsistencyChecker()

        rvfi1 = make_rvfi(
            insn=encode_r(0x00, 2, 1, 0, 3),
            rs1_addr=1, rs1_rdata=5,
            rs2_addr=2, rs2_rdata=3,
            rd_addr=3, rd_wdata=8,
            pc_rdata=0, pc_wdata=4,
        )
        checker.check_and_update(rvfi1)

        # Read x3 with wrong value
        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 3, 0, 4),
            rs1_addr=3, rs1_rdata=999,  # Wrong! Shadow says 8
            rs2_addr=0, rs2_rdata=0,
            rd_addr=4, rd_wdata=999,
            pc_rdata=4, pc_wdata=8,
        )
        violations = checker.check_and_update(rvfi2)
        assert any(v.field == 'rs1_rdata' for v in violations), \
            "Validator must detect register inconsistency"

    def test_pc_discontinuity_without_intr(self):
        """PC mismatch without intr flag must be detected."""
        checker = ConsistencyChecker()

        rvfi1 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x100, pc_wdata=0x104,
        )
        checker.check_and_update(rvfi1)

        # PC jumps without intr set
        rvfi2 = make_rvfi(
            insn=encode_r(0x00, 0, 0, 0, 0),
            pc_rdata=0x300, pc_wdata=0x304,
            intr=0,
        )
        violations = checker.check_and_update(rvfi2)
        assert any(v.field == 'pc_rdata' for v in violations), \
            "Validator must detect PC discontinuity without intr flag"

    def test_wrong_branch_target(self):
        """Branch to wrong target must be detected."""
        rvfi = make_rvfi(
            insn=encode_b(8, 0, 0, 0),  # BEQ x0, x0, +8 (always taken)
            rs1_addr=0, rs1_rdata=0,
            rs2_addr=0, rs2_rdata=0,
            pc_rdata=0x100, pc_wdata=0x200,  # Wrong! Should be 0x108
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'pc_wdata' for v in violations), \
            "Validator must detect wrong branch target"

    def test_wrong_load_mask(self):
        """Load with wrong rmask must be detected."""
        rvfi = make_rvfi(
            insn=encode_i(0, 1, 2, 3, 0x03),  # LW
            rs1_addr=1, rs1_rdata=0x1000,
            rd_addr=3, rd_wdata=42,
            pc_rdata=0, pc_wdata=4,
            mem_addr=0x1000, mem_rmask=0x3, mem_rdata=42,  # Wrong mask for LW!
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'mem_rmask' for v in violations), \
            "Validator must detect wrong load mask"


# ============================================================================
# M-extension negative tests: prevent no-op or trivially broken implementations
# ============================================================================

class TestMExtNegative:
    """Ensure M-extension validator correctly catches errors.

    These prevent the agent from implementing M-extension as a no-op
    (returning no violations for any input).
    """

    def test_mul_wrong_result(self):
        """MUL with wrong result must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=6,
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=43,  # Wrong! 6*7=42
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong MUL result"

    def test_mulh_wrong_result(self):
        """MULH with wrong upper bits must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(1, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0x10000,
            rs2_addr=2, rs2_rdata=0x10000,
            rd_addr=3, rd_wdata=0,  # Wrong! Should be 1
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong MULH result"

    def test_mulhsu_wrong_sign(self):
        """MULHSU with unsigned-treated rs1 must be detected."""
        # If implementation treats rs1 as unsigned instead of signed,
        # MULHSU(0xFFFFFFFF, 0xFFFFFFFF) would give 0xFFFFFFFE (MULHU)
        # instead of 0xFFFFFFFF (correct MULHSU with signed -1)
        rvfi = make_rvfi(
            insn=encode_m(2, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0xFFFFFFFE,  # Wrong! MULHU result, not MULHSU
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must distinguish MULHSU from MULHU"

    def test_div_wrong_zero_result(self):
        """DIV by zero returning 0 instead of -1 must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0,  # Wrong! Should be 0xFFFFFFFF
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong DIV-by-zero result"

    def test_rem_wrong_overflow(self):
        """REM overflow returning non-zero must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(6, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0x80000000,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0x80000000,  # Wrong! Should be 0
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong REM overflow result"

    def test_div_wrong_rounding(self):
        """DIV with floor-division rounding instead of truncation must be detected.

        -13 / 5: truncated = -2 (correct), floored = -3 (wrong).
        """
        rvfi = make_rvfi(
            insn=encode_m(4, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFF3,  # -13
            rs2_addr=2, rs2_rdata=5,
            rd_addr=3, rd_wdata=mask32(-3),  # Wrong! Should be mask32(-2)
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong DIV rounding"

    def test_mulhu_wrong_result(self):
        """MULHU with wrong result must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(3, 2, 1, 3),
            rs1_addr=1, rs1_rdata=0xFFFFFFFF,
            rs2_addr=2, rs2_rdata=0xFFFFFFFF,
            rd_addr=3, rd_wdata=0xFFFFFFFF,  # Wrong! Should be 0xFFFFFFFE
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong MULHU result"

    def test_divu_wrong_zero_result(self):
        """DIVU by zero returning 0 instead of 0xFFFFFFFF must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(5, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0,  # Wrong! Should be 0xFFFFFFFF
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong DIVU-by-zero result"

    def test_remu_wrong_zero_result(self):
        """REMU by zero returning 0 instead of dividend must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(7, 2, 1, 3),
            rs1_addr=1, rs1_rdata=42,
            rs2_addr=2, rs2_rdata=0,
            rd_addr=3, rd_wdata=0,  # Wrong! Should be 42
            pc_rdata=0, pc_wdata=4,
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'rd_wdata' for v in violations), \
            "Validator must detect wrong REMU-by-zero result"

    def test_m_ext_wrong_pc(self):
        """M-extension with wrong next PC must be detected."""
        rvfi = make_rvfi(
            insn=encode_m(0, 2, 1, 3),
            rs1_addr=1, rs1_rdata=6,
            rs2_addr=2, rs2_rdata=7,
            rd_addr=3, rd_wdata=42,
            pc_rdata=0x100, pc_wdata=0x108,  # Wrong! Should be 0x104
        )
        violations = check_instruction(rvfi)
        assert any(v.field == 'pc_wdata' for v in violations), \
            "Validator must detect wrong M-ext next PC"
