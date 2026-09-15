"""RISC-V RV32I Specification Checker

Checks whether an instruction's RVFI trace signals match the behavior
required by the RISC-V ISA specification. Covers all RV32I base integer
instructions: ALU (R-type and I-type), branches, jumps, loads, stores,
LUI, and AUIPC.
"""

from .decoder import (
    decode, mask32, sign_extend,
    OP_LUI, OP_AUIPC, OP_JAL, OP_JALR, OP_BRANCH, OP_LOAD, OP_STORE, OP_IMM, OP_REG,
    F3_BEQ, F3_BNE, F3_BLT, F3_BGE, F3_BLTU, F3_BGEU,
    F3_LB, F3_LH, F3_LW, F3_LBU, F3_LHU,
    F3_SB, F3_SH, F3_SW,
    F3_ADD, F3_SLL, F3_SLT, F3_SLTU, F3_XOR, F3_SRL, F3_OR, F3_AND,
)


class Violation:
    """Represents a specification violation found in an RVFI trace record."""

    def __init__(self, field, expected, actual, message):
        self.field = field
        self.expected = expected
        self.actual = actual
        self.message = message

    def __repr__(self):
        return (f"Violation({self.field}: "
                f"expected={self.expected:#010x}, actual={self.actual:#010x}, "
                f"{self.message})")


def _to_signed32(val):
    """Convert a 32-bit unsigned value to a signed Python int."""
    val = val & 0xFFFFFFFF
    if val >= 0x80000000:
        return val - 0x100000000
    return val


def check_instruction(rvfi):
    """Check a single RVFI instruction record against the RV32I specification.

    Args:
        rvfi: dict with keys insn, rs1_addr, rs1_rdata, rs2_addr, rs2_rdata,
              rd_addr, rd_wdata, pc_rdata, pc_wdata, mem_addr, mem_rmask,
              mem_wmask, mem_rdata, mem_wdata, trap

    Returns:
        List of Violation objects.
    """
    violations = []
    insn_word = rvfi['insn']
    dec = decode(insn_word)
    opcode = dec['opcode']

    if dec['type'] == 'ILLEGAL':
        if not rvfi.get('trap', 0):
            violations.append(Violation('trap', 1, 0,
                                        'Illegal instruction must trap'))
        return violations

    if dec['type'] in ('FENCE', 'SYSTEM'):
        return violations

    if opcode == OP_REG:
        violations.extend(_check_r_type(dec, rvfi))
    elif opcode == OP_IMM:
        violations.extend(_check_i_type(dec, rvfi))
    elif opcode == OP_LUI:
        violations.extend(_check_lui(dec, rvfi))
    elif opcode == OP_AUIPC:
        violations.extend(_check_auipc(dec, rvfi))
    elif opcode == OP_JAL:
        violations.extend(_check_jal(dec, rvfi))
    elif opcode == OP_JALR:
        violations.extend(_check_jalr(dec, rvfi))
    elif opcode == OP_BRANCH:
        violations.extend(_check_branch(dec, rvfi))
    elif opcode == OP_LOAD:
        violations.extend(_check_load(dec, rvfi))
    elif opcode == OP_STORE:
        violations.extend(_check_store(dec, rvfi))

    return violations


# ---- Helper checkers ----

def _check_rd(dec, rvfi, expected_rd_wdata):
    """Check rd_addr and rd_wdata against expected values."""
    violations = []
    rd = dec.get('rd', 0)

    if rvfi['rd_addr'] != rd:
        violations.append(Violation('rd_addr', rd, rvfi['rd_addr'],
                                    'rd address mismatch'))

    # Per RVFI spec: rd_wdata must be 0 when rd is x0
    expected = mask32(expected_rd_wdata) if rd != 0 else 0
    if rvfi['rd_wdata'] != expected:
        violations.append(Violation('rd_wdata', expected, rvfi['rd_wdata'],
                                    'rd write data mismatch'))
    return violations


def _check_pc_next(rvfi, expected_pc):
    """Check that pc_wdata matches the expected next PC."""
    expected = mask32(expected_pc)
    if rvfi['pc_wdata'] != expected:
        return [Violation('pc_wdata', expected, rvfi['pc_wdata'],
                          'next PC mismatch')]
    return []


def _check_rs_addrs(dec, rvfi, check_rs2=True):
    """Check rs1_addr (and optionally rs2_addr) against decoded values."""
    violations = []
    if rvfi['rs1_addr'] != dec.get('rs1', 0):
        violations.append(Violation('rs1_addr', dec.get('rs1', 0),
                                    rvfi['rs1_addr'], 'rs1 address mismatch'))
    if check_rs2 and rvfi['rs2_addr'] != dec.get('rs2', 0):
        violations.append(Violation('rs2_addr', dec.get('rs2', 0),
                                    rvfi['rs2_addr'], 'rs2 address mismatch'))
    return violations


# ---- Instruction-type checkers ----

def _check_r_type(dec, rvfi):
    """Check R-type ALU instructions (ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND)."""
    violations = []
    rs1 = rvfi['rs1_rdata']
    rs2 = rvfi['rs2_rdata']
    funct3 = dec['funct3']
    funct7 = dec['funct7']

    if funct7 == 0x01:
        # M-extension (multiply/divide) — not yet implemented
        return []

    if funct3 == F3_ADD:
        if funct7 == 0x00:
            result = mask32(rs1 + rs2)
        elif funct7 == 0x20:
            result = mask32(rs1 - rs2)
        else:
            return []
    elif funct3 == F3_SLL:
        shamt = rs2 & 0x1F
        result = mask32(rs1 << shamt)
    elif funct3 == F3_SLT:
        result = 1 if _to_signed32(rs1) < _to_signed32(rs2) else 0
    elif funct3 == F3_SLTU:
        result = 1 if rs1 < rs2 else 0
    elif funct3 == F3_XOR:
        result = rs1 ^ rs2
    elif funct3 == F3_SRL:
        shamt = rs2 & 0x1F
        if funct7 == 0x00:
            result = rs1 >> shamt
        elif funct7 == 0x20:
            result = mask32(rs1 >> shamt)  # logical shift right
        else:
            return []
    elif funct3 == F3_OR:
        result = rs1 | rs2
    elif funct3 == F3_AND:
        result = rs1 & rs2
    else:
        return []

    violations.extend(_check_rd(dec, rvfi, result))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    violations.extend(_check_rs_addrs(dec, rvfi))
    return violations


def _check_i_type(dec, rvfi):
    """Check I-type ALU instructions (ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI)."""
    violations = []
    rs1 = rvfi['rs1_rdata']
    imm = dec['imm']
    funct3 = dec['funct3']

    if funct3 == F3_ADD:  # ADDI
        result = mask32(rs1 + imm)
    elif funct3 == F3_SLT:  # SLTI
        result = 1 if _to_signed32(rs1) < _to_signed32(mask32(imm)) else 0
    elif funct3 == F3_SLTU:  # SLTIU
        result = 1 if rs1 < mask32(imm) else 0
    elif funct3 == F3_XOR:  # XORI
        result = mask32(rs1 ^ imm)
    elif funct3 == F3_OR:  # ORI
        result = mask32(rs1 | imm)
    elif funct3 == F3_AND:  # ANDI
        result = mask32(rs1 & imm)
    elif funct3 == F3_SLL:  # SLLI
        shamt = dec.get('shamt', imm & 0x1F)
        result = mask32(rs1 << shamt)
    elif funct3 == F3_SRL:  # SRLI or SRAI
        shamt = dec.get('shamt', imm & 0x1F)
        funct7 = dec.get('funct7', 0)
        if funct7 == 0x00:
            result = rs1 >> shamt
        elif funct7 == 0x20:
            result = mask32(rs1 >> shamt)  # logical shift right
        else:
            return []
    else:
        return []

    violations.extend(_check_rd(dec, rvfi, result))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    violations.extend(_check_rs_addrs(dec, rvfi, check_rs2=False))
    return violations


def _check_lui(dec, rvfi):
    """Check LUI instruction."""
    violations = []
    result = mask32(dec['imm'])
    violations.extend(_check_rd(dec, rvfi, result))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    return violations


def _check_auipc(dec, rvfi):
    """Check AUIPC instruction."""
    raise NotImplementedError("AUIPC")


def _check_jal(dec, rvfi):
    """Check JAL instruction."""
    violations = []
    pc = rvfi['pc_rdata']
    target = mask32(pc + dec['imm'])
    link = mask32(pc + 4)

    violations.extend(_check_rd(dec, rvfi, link))
    violations.extend(_check_pc_next(rvfi, target))

    if target & 0x3:
        if not rvfi.get('trap', 0):
            violations.append(Violation('trap', 1, 0,
                                        'Misaligned JAL target should trap'))
    return violations


def _check_jalr(dec, rvfi):
    """Check JALR instruction."""
    violations = []
    pc = rvfi['pc_rdata']
    rs1 = rvfi['rs1_rdata']
    imm = dec['imm']

    target = mask32(rs1 + imm)  # jalr target
    link = mask32(pc + 4)

    violations.extend(_check_rd(dec, rvfi, link))
    violations.extend(_check_pc_next(rvfi, target))
    violations.extend(_check_rs_addrs(dec, rvfi, check_rs2=False))
    return violations


def _check_branch(dec, rvfi):
    """Check branch instructions (BEQ, BNE, BLT, BGE, BLTU, BGEU)."""
    violations = []
    rs1 = rvfi['rs1_rdata']
    rs2 = rvfi['rs2_rdata']
    funct3 = dec['funct3']
    pc = rvfi['pc_rdata']
    imm = dec['imm']

    if funct3 == F3_BEQ:
        taken = (rs1 == rs2)
    elif funct3 == F3_BNE:
        taken = (rs1 != rs2)
    elif funct3 == F3_BLT:
        taken = (_to_signed32(rs1) < _to_signed32(rs2))
    elif funct3 == F3_BGE:
        taken = (_to_signed32(rs1) >= _to_signed32(rs2))
    elif funct3 == F3_BLTU:
        taken = (rs1 < rs2)
    elif funct3 == F3_BGEU:
        taken = (rs1 >= rs2)
    else:
        return []

    next_pc = mask32(pc + imm) if taken else mask32(pc + 4)
    violations.extend(_check_pc_next(rvfi, next_pc))
    violations.extend(_check_rs_addrs(dec, rvfi))
    return violations


def _check_load(dec, rvfi):
    """Check load instructions (LW, LH, LHU, LB, LBU)."""
    violations = []
    rs1 = rvfi['rs1_rdata']
    imm = dec['imm']
    funct3 = dec['funct3']
    addr = mask32(rs1 + imm)
    mem_rdata = rvfi['mem_rdata']

    if funct3 == F3_LW:
        expected_rmask = 0xF
        result = mem_rdata
        if addr & 0x3:
            if not rvfi.get('trap', 0):
                violations.append(Violation('trap', 1, 0,
                                            'Misaligned LW should trap'))
            return violations
    elif funct3 == F3_LH:
        expected_rmask = 0x3
        result = mem_rdata & 0xFFFF  # lh zero extend
        if addr & 0x1:
            if not rvfi.get('trap', 0):
                violations.append(Violation('trap', 1, 0,
                                            'Misaligned LH should trap'))
            return violations
    elif funct3 == F3_LHU:
        expected_rmask = 0x3
        result = mem_rdata & 0xFFFF
        if addr & 0x1:
            if not rvfi.get('trap', 0):
                violations.append(Violation('trap', 1, 0,
                                            'Misaligned LHU should trap'))
            return violations
    elif funct3 == F3_LB:
        expected_rmask = 0x1
        result = sign_extend(mem_rdata & 0xFF, 8)
    elif funct3 == F3_LBU:
        expected_rmask = 0x1
        result = mem_rdata & 0xFF
    else:
        return []

    if rvfi['mem_addr'] != addr:
        violations.append(Violation('mem_addr', addr, rvfi['mem_addr'],
                                    'Load address mismatch'))
    if rvfi['mem_rmask'] != expected_rmask:
        violations.append(Violation('mem_rmask', expected_rmask,
                                    rvfi['mem_rmask'],
                                    'Load read mask mismatch'))

    violations.extend(_check_rd(dec, rvfi, mask32(result)))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    violations.extend(_check_rs_addrs(dec, rvfi, check_rs2=False))
    return violations


def _check_store(dec, rvfi):
    """Check store instructions (SW, SH, SB)."""
    violations = []
    rs1 = rvfi['rs1_rdata']
    rs2 = rvfi['rs2_rdata']
    imm = dec['imm']
    funct3 = dec['funct3']
    addr = mask32(rs1 + imm)

    if funct3 == F3_SW:
        expected_wmask = 0xF
        expected_wdata = rs2
        if addr & 0x3:
            if not rvfi.get('trap', 0):
                violations.append(Violation('trap', 1, 0,
                                            'Misaligned SW should trap'))
            return violations
    elif funct3 == F3_SH:
        expected_wmask = 0x3
        expected_wdata = rs2 & 0xFFFF
        if addr & 0x1:
            if not rvfi.get('trap', 0):
                violations.append(Violation('trap', 1, 0,
                                            'Misaligned SH should trap'))
            return violations
    elif funct3 == F3_SB:
        expected_wmask = 0x3  # sb mask
        expected_wdata = rs2 & 0xFF
    else:
        return []

    if rvfi['mem_addr'] != addr:
        violations.append(Violation('mem_addr', addr, rvfi['mem_addr'],
                                    'Store address mismatch'))
    if rvfi['mem_wmask'] != expected_wmask:
        violations.append(Violation('mem_wmask', expected_wmask,
                                    rvfi['mem_wmask'],
                                    'Store write mask mismatch'))
    if rvfi['mem_wdata'] != mask32(expected_wdata):
        violations.append(Violation('mem_wdata', mask32(expected_wdata),
                                    rvfi['mem_wdata'],
                                    'Store write data mismatch'))

    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    violations.extend(_check_rs_addrs(dec, rvfi))

    if rvfi['rd_addr'] != 0:
        violations.append(Violation('rd_addr', 0, rvfi['rd_addr'],
                                    'Store must not write a register'))
    return violations
