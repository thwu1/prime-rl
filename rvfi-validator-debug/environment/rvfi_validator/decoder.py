"""RISC-V RV32I Instruction Decoder

Decodes 32-bit RISC-V instruction words into their constituent fields
according to the RISC-V ISA specification. Supports R, I, S, B, U, and J
instruction formats.
"""

# RV32I Opcodes
OP_LUI    = 0b0110111
OP_AUIPC  = 0b0010111
OP_JAL    = 0b1101111
OP_JALR   = 0b1100111
OP_BRANCH = 0b1100011
OP_LOAD   = 0b0000011
OP_STORE  = 0b0100011
OP_IMM    = 0b0010011
OP_REG    = 0b0110011
OP_FENCE  = 0b0001111
OP_SYSTEM = 0b1110011

# Funct3 for branches
F3_BEQ  = 0b000
F3_BNE  = 0b001
F3_BLT  = 0b100
F3_BGE  = 0b101
F3_BLTU = 0b110
F3_BGEU = 0b111

# Funct3 for loads
F3_LB  = 0b000
F3_LH  = 0b001
F3_LW  = 0b010
F3_LBU = 0b100
F3_LHU = 0b101

# Funct3 for stores
F3_SB = 0b000
F3_SH = 0b001
F3_SW = 0b010

# Funct3 for ALU operations
F3_ADD  = 0b000  # ADD/SUB (distinguished by funct7)
F3_SLL  = 0b001
F3_SLT  = 0b010
F3_SLTU = 0b011
F3_XOR  = 0b100
F3_SRL  = 0b101  # SRL/SRA (distinguished by funct7)
F3_OR   = 0b110
F3_AND  = 0b111

XLEN = 32


def sign_extend(value, bits):
    """Sign-extend a value of given bit width to a full Python int."""
    sign_bit = 1 << (bits - 1)
    return (value & ((1 << bits) - 1) ^ sign_bit) - sign_bit


def mask32(value):
    """Mask a value to 32 bits (unsigned representation)."""
    return value & 0xFFFFFFFF


def decode(insn):
    """Decode a 32-bit RV32I instruction word.

    Returns a dictionary with decoded fields including type, opcode,
    and format-specific fields (rd, rs1, rs2, funct3, funct7, imm, shamt).
    """
    opcode = insn & 0x7F
    result = {'opcode': opcode, 'raw': insn}

    if opcode == OP_REG:
        # R-type: funct7 | rs2 | rs1 | funct3 | rd | opcode
        result['type'] = 'R'
        result['funct7'] = (insn >> 25) & 0x7F
        result['rs2'] = (insn >> 20) & 0x1F
        result['rs1'] = (insn >> 15) & 0x1F
        result['funct3'] = (insn >> 12) & 0x7
        result['rd'] = (insn >> 7) & 0x1F

    elif opcode in (OP_LOAD, OP_JALR, OP_IMM):
        # I-type: imm[11:0] | rs1 | funct3 | rd | opcode
        result['type'] = 'I'
        result['imm'] = sign_extend((insn >> 20) & 0xFFF, 12)
        result['rs1'] = (insn >> 15) & 0x1F
        result['funct3'] = (insn >> 12) & 0x7
        result['rd'] = (insn >> 7) & 0x1F
        # Shift-immediate instructions encode funct7 and shamt in the imm field
        if opcode == OP_IMM and result['funct3'] in (F3_SLL, F3_SRL):
            result['funct7'] = (insn >> 25) & 0x7F
            result['shamt'] = (insn >> 20) & 0x1F

    elif opcode == OP_STORE:
        # S-type: imm[11:5] | rs2 | rs1 | funct3 | imm[4:0] | opcode
        result['type'] = 'S'
        raw_imm = ((insn >> 25) & 0x7F) << 5 | ((insn >> 7) & 0x1F)
        result['imm'] = raw_imm  # S-type immediate
        result['rs2'] = (insn >> 20) & 0x1F
        result['rs1'] = (insn >> 15) & 0x1F
        result['funct3'] = (insn >> 12) & 0x7

    elif opcode == OP_BRANCH:
        # B-type: imm[12|10:5] | rs2 | rs1 | funct3 | imm[4:1|11] | opcode
        result['type'] = 'B'
        imm_12 = (insn >> 31) & 1
        imm_11 = (insn >> 7) & 1
        imm_10_5 = (insn >> 25) & 0x3F
        imm_4_1 = (insn >> 8) & 0xF
        raw_imm = (imm_12 << 12) | (imm_11 << 11) | (imm_10_5 << 5) | (imm_4_1 << 1)
        result['imm'] = sign_extend(raw_imm, 12)  # B-type immediate
        result['rs2'] = (insn >> 20) & 0x1F
        result['rs1'] = (insn >> 15) & 0x1F
        result['funct3'] = (insn >> 12) & 0x7

    elif opcode in (OP_LUI, OP_AUIPC):
        # U-type: imm[31:12] | rd | opcode
        result['type'] = 'U'
        raw = insn & 0xFFFFF000
        result['imm'] = raw if raw < 0x80000000 else raw - 0x100000000
        result['rd'] = (insn >> 7) & 0x1F

    elif opcode == OP_JAL:
        # J-type: imm[20|10:1|11|19:12] | rd | opcode
        result['type'] = 'J'
        imm_20 = (insn >> 31) & 1
        imm_10_1 = (insn >> 21) & 0x3FF
        imm_11 = (insn >> 20) & 1
        imm_19_12 = (insn >> 12) & 0xFF
        raw_imm = (imm_20 << 20) | (imm_19_12 << 12) | (imm_11 << 11) | (imm_10_1 << 1)
        result['imm'] = sign_extend(raw_imm, 21)
        result['rd'] = (insn >> 7) & 0x1F

    elif opcode == OP_SYSTEM:
        result['type'] = 'SYSTEM'
        result['funct3'] = (insn >> 12) & 0x7
        result['rd'] = (insn >> 7) & 0x1F
        result['rs1'] = (insn >> 15) & 0x1F
        result['imm'] = (insn >> 20) & 0xFFF

    elif opcode == OP_FENCE:
        result['type'] = 'FENCE'

    else:
        result['type'] = 'ILLEGAL'

    return result
