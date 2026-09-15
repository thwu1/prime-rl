#!/usr/bin/env python3
"""Generate the 8086 division microcode ROM binary.

This script creates /app/microcode_rom.bin containing the packed 21-bit
micro-instructions for the 8086's division routines, encoded according
to the format documented in rom_format.md.

"""

# Register codes (5 bits)
REG = {
    'tmpA': 0x00, 'tmpB': 0x01, 'tmpC': 0x02, 'SIGMA': 0x03,
    'AX': 0x04, 'DX': 0x05, 'AH': 0x06, 'AL': 0x07,
    'M': 0x08, 'NONE': 0x1F,
}

# Type codes (3 bits)
TYPE = {
    'ALU': 0, 'SJMP': 1, 'LJMP': 2, 'LCALL': 3,
    'SPECIAL': 4, 'RETURN': 5, 'TERMINAL': 6, 'MOVE': 7,
}

# ALU operation codes (3 bits, in operand[6:4])
ALU = {'SUBT': 0, 'RCL': 1, 'NEG': 2, 'COM1': 3, 'INC': 4}

# Condition codes (3 bits, in operand[6:4] for jumps)
COND = {'UNC': 0, 'CY': 1, 'NCY': 2, 'NCZ': 3, 'F1': 4, 'X0': 5}

# Special operation codes (in operand[6:0])
SPEC = {'MAXC': 1, 'RCY': 2, 'CF1': 3, 'CCOF': 4, 'SCOF': 5}

# Routine IDs for long jumps/calls (in operand[3:0])
ROUT = {'INT0': 0, 'CORD': 1, 'PREIDIV': 2, 'POSTIDIV': 3}


def enc(src, dst, f, typ, operand):
    """Encode a 21-bit micro-instruction."""
    s = REG[src]
    d = REG[dst]
    t = TYPE[typ]
    return (s << 16) | (d << 11) | (f << 10) | (t << 7) | (operand & 0x7F)


def alu(op, reg):
    return (ALU[op] << 4) | REG[reg]


def sjmp(cond, target):
    return (COND[cond] << 4) | (target & 0xF)


def ljmp(cond, routine):
    return (COND[cond] << 4) | ROUT[routine]


# ═══════════════════════════════════════════════════════════════════
# Microcode routines — encoded from Ken Shirriff's reverse-engineered
# 8086 division microcode (CORD, PREIDIV, POSTIDIV, top-level dispatch)
# ═══════════════════════════════════════════════════════════════════

CORD = [
    enc('NONE', 'NONE', 0, 'ALU',     alu('SUBT', 'tmpA')),      # 0: SUBT tmpA
    enc('SIGMA','NONE', 1, 'SPECIAL',  SPEC['MAXC']),              # 1: Σ→_, MAXC, F
    enc('NONE', 'NONE', 0, 'LJMP',    ljmp('NCY', 'INT0')),       # 2: JMP NCY→INT0
    enc('NONE', 'NONE', 0, 'ALU',     alu('RCL', 'tmpC')),        # 3: RCL tmpC
    enc('SIGMA','tmpC', 0, 'ALU',     alu('RCL', 'tmpA')),        # 4: Σ→tmpC, RCL tmpA
    enc('SIGMA','tmpA', 0, 'ALU',     alu('SUBT', 'tmpA')),       # 5: Σ→tmpA, SUBT tmpA
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('CY', 13)),            # 6: JMPS CY→13
    enc('SIGMA','NONE', 1, 'MOVE',    0),                          # 7: Σ→_, F
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('NCY', 14)),           # 8: JMPS NCY→14
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('NCZ', 3)),            # 9: JMPS NCZ→3
    enc('NONE', 'NONE', 0, 'ALU',     alu('RCL', 'tmpC')),        # 10: RCL tmpC
    enc('SIGMA','tmpC', 0, 'ALU',     alu('RCL', 'tmpC')),        # 11: Σ→tmpC, RCL tmpC
    enc('SIGMA','NONE', 0, 'RETURN',  0),                          # 12: Σ→_, RTN
    enc('NONE', 'NONE', 0, 'SPECIAL', SPEC['RCY']),                # 13: RCY
    enc('SIGMA','tmpA', 0, 'SJMP',    sjmp('NCZ', 3)),            # 14: Σ→tmpA, JMPS NCZ→3
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('UNC', 10)),           # 15: JMPS UNC→10
]

PREIDIV = [
    enc('SIGMA','NONE', 0, 'MOVE',    0),                          # 0: Σ→_
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('NCY', 7)),            # 1: JMPS NCY→7
    enc('NONE', 'NONE', 0, 'ALU',     alu('NEG', 'tmpC')),        # 2: NEG tmpC
    enc('SIGMA','tmpC', 1, 'ALU',     alu('COM1', 'tmpA')),       # 3: Σ→tmpC, COM1 tmpA, F
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('CY', 6)),             # 4: JMPS CY→6
    enc('NONE', 'NONE', 0, 'ALU',     alu('NEG', 'tmpA')),        # 5: NEG tmpA
    enc('SIGMA','tmpA', 0, 'SPECIAL', SPEC['CF1']),                # 6: Σ→tmpA, CF1
    enc('NONE', 'NONE', 0, 'ALU',     alu('RCL', 'tmpB')),        # 7: RCL tmpB
    enc('SIGMA','NONE', 0, 'ALU',     alu('NEG', 'tmpB')),        # 8: Σ→_, NEG tmpB
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('NCY', 11)),           # 9: JMPS NCY→11
    enc('SIGMA','tmpB', 0, 'RETURN',  SPEC['CF1']),                # 10: Σ→tmpB, CF1+RTN
    enc('NONE', 'NONE', 0, 'RETURN',  0),                          # 11: RTN
]

POSTIDIV = [
    enc('NONE', 'NONE', 0, 'LJMP',    ljmp('NCY', 'INT0')),       # 0: JMP NCY→INT0
    enc('NONE', 'NONE', 0, 'ALU',     alu('RCL', 'tmpB')),        # 1: RCL tmpB
    enc('SIGMA','NONE', 0, 'ALU',     alu('NEG', 'tmpA')),        # 2: Σ→_, NEG tmpA
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('NCY', 5)),            # 3: JMPS NCY→5
    enc('SIGMA','tmpA', 0, 'MOVE',    0),                          # 4: Σ→tmpA
    enc('NONE', 'NONE', 0, 'ALU',     alu('INC', 'tmpC')),        # 5: INC tmpC
    enc('NONE', 'NONE', 0, 'SJMP',    sjmp('F1', 8)),             # 6: JMPS F1→8
    enc('NONE', 'NONE', 0, 'ALU',     alu('COM1', 'tmpC')),       # 7: COM1 tmpC
    enc('NONE', 'NONE', 0, 'RETURN',  SPEC['CCOF']),               # 8: CCOF+RTN
]

DIV_WORD = [
    enc('DX',   'tmpA', 0, 'MOVE',    0),                          # 0: DX→tmpA
    enc('AX',   'tmpC', 0, 'ALU',     alu('RCL', 'tmpA')),        # 1: AX→tmpC, RCL tmpA
    enc('M',    'tmpB', 0, 'LCALL',   ljmp('X0', 'PREIDIV')),     # 2: M→tmpB, CALL X0→PREIDIV
    enc('NONE', 'NONE', 0, 'LCALL',   ljmp('UNC', 'CORD')),       # 3: CALL UNC→CORD
    enc('NONE', 'NONE', 0, 'ALU',     alu('COM1', 'tmpC')),       # 4: COM1 tmpC
    enc('DX',   'tmpB', 0, 'LCALL',   ljmp('X0', 'POSTIDIV')),    # 5: DX→tmpB, CALL X0→POSTIDIV
    enc('SIGMA','AX',   0, 'TERMINAL', 0),                         # 6: Σ→AX, NXT
    enc('tmpA', 'DX',   0, 'TERMINAL', 1),                         # 7: tmpA→DX, RNI
]

DIV_BYTE = [
    enc('AH',   'tmpA', 0, 'MOVE',    0),                          # 0: AH→tmpA
    enc('AL',   'tmpC', 0, 'ALU',     alu('RCL', 'tmpA')),        # 1: AL→tmpC, RCL tmpA
    enc('M',    'tmpB', 0, 'LCALL',   ljmp('X0', 'PREIDIV')),     # 2: M→tmpB, CALL X0→PREIDIV
    enc('NONE', 'NONE', 0, 'LCALL',   ljmp('UNC', 'CORD')),       # 3: CALL UNC→CORD
    enc('NONE', 'NONE', 0, 'ALU',     alu('COM1', 'tmpC')),       # 4: COM1 tmpC
    enc('AH',   'tmpB', 0, 'LCALL',   ljmp('X0', 'POSTIDIV')),    # 5: AH→tmpB, CALL X0→POSTIDIV
    enc('SIGMA','AL',   0, 'TERMINAL', 0),                         # 6: Σ→AL, NXT
    enc('tmpA', 'AH',   0, 'TERMINAL', 1),                         # 7: tmpA→AH, RNI
]

ROUTINES = [
    (0, 'CORD',     CORD),
    (1, 'PREIDIV',  PREIDIV),
    (2, 'POSTIDIV', POSTIDIV),
    (3, 'DIV_WORD', DIV_WORD),
    (4, 'DIV_BYTE', DIV_BYTE),
]


def pack_bitstream(instructions):
    """Pack 21-bit instructions into bytes, MSB first, no inter-instruction gaps."""
    bits = []
    for inst in instructions:
        for i in range(20, -1, -1):
            bits.append((inst >> i) & 1)
    # Pad to byte boundary
    while len(bits) % 8:
        bits.append(0)
    result = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        result.append(byte)
    return bytes(result)


def main():
    data = bytearray()
    # Header
    data.extend(b'UROM')          # Magic (4 bytes)
    data.append(0x01)              # Version (1 byte)
    data.append(len(ROUTINES))     # Routine count (1 byte)

    for rid, name, insts in ROUTINES:
        data.append(rid)           # Routine ID (1 byte)
        data.append(len(insts))    # Instruction count (1 byte)
        packed = pack_bitstream(insts)
        data.extend(packed)

    with open('/app/microcode_rom.bin', 'wb') as f:
        f.write(data)

    total_insts = sum(len(insts) for _, _, insts in ROUTINES)
    print(f"Generated ROM: {len(data)} bytes, {total_insts} micro-instructions across {len(ROUTINES)} routines")


if __name__ == '__main__':
    main()
