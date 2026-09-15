#!/usr/bin/env python3
"""
Decode the 8086 microcode ROM binary and produce a human-readable disassembly.

Reads /app/microcode_rom.bin (packed 21-bit micro-instructions) and writes
/app/disassembly.txt.

"""

# Register names (5-bit codes)
REG_NAMES = {
    0x00: 'tmpA', 0x01: 'tmpB', 0x02: 'tmpC', 0x03: 'SIGMA',
    0x04: 'AX', 0x05: 'DX', 0x06: 'AH', 0x07: 'AL',
    0x08: 'M', 0x1F: 'NONE',
}

# Type names (3-bit codes)
TYPE_NAMES = {
    0: 'ALU', 1: 'SJMP', 2: 'LJMP', 3: 'LCALL',
    4: 'SPECIAL', 5: 'RETURN', 6: 'TERMINAL', 7: 'MOVE',
}

# ALU operation names
ALU_NAMES = {0: 'SUBT', 1: 'RCL', 2: 'NEG', 3: 'COM1', 4: 'INC'}

# Condition names
COND_NAMES = {0: 'UNC', 1: 'CY', 2: 'NCY', 3: 'NCZ', 4: 'F1', 5: 'X0'}

# Special operation names
SPEC_NAMES = {1: 'MAXC', 2: 'RCY', 3: 'CF1', 4: 'CCOF', 5: 'SCOF'}

# Routine names by ID
ROUTINE_NAMES = {
    0: 'CORD', 1: 'PREIDIV', 2: 'POSTIDIV', 3: 'DIV_WORD', 4: 'DIV_BYTE',
}

# Target routine names for jumps/calls
TARGET_NAMES = {0: 'INT0', 1: 'CORD', 2: 'PREIDIV', 3: 'POSTIDIV'}


def extract_bits(data, bit_offset, num_bits):
    """Extract num_bits from byte array starting at bit_offset (MSB first)."""
    value = 0
    for i in range(num_bits):
        byte_idx = (bit_offset + i) // 8
        bit_idx = 7 - ((bit_offset + i) % 8)
        if byte_idx < len(data):
            value = (value << 1) | ((data[byte_idx] >> bit_idx) & 1)
        else:
            value = value << 1
    return value


def decode_instruction(inst_val):
    """Decode a 21-bit instruction value into (src, dst, f, type, operand)."""
    src = (inst_val >> 16) & 0x1F
    dst = (inst_val >> 11) & 0x1F
    f = (inst_val >> 10) & 1
    typ = (inst_val >> 7) & 7
    operand = inst_val & 0x7F
    return src, dst, f, typ, operand


def format_instruction(src, dst, f, typ, operand):
    """Format a decoded instruction as human-readable text."""
    src_name = REG_NAMES.get(src, f'R{src}')
    dst_name = REG_NAMES.get(dst, f'R{dst}')
    f_str = '  F' if f else ''

    if typ == 0:  # ALU
        alu_op = (operand >> 4) & 7
        alu_reg = operand & 0xF
        alu_name = ALU_NAMES.get(alu_op, f'OP{alu_op}')
        reg_name = REG_NAMES.get(alu_reg, f'R{alu_reg}')
        action = f'[ALU] {alu_name} {reg_name}'
    elif typ == 1:  # SJMP
        cond = (operand >> 4) & 7
        target = operand & 0xF
        cond_name = COND_NAMES.get(cond, f'C{cond}')
        action = f'[SJMP] {cond_name} -> {target}'
    elif typ == 2:  # LJMP
        cond = (operand >> 4) & 7
        target = operand & 0xF
        cond_name = COND_NAMES.get(cond, f'C{cond}')
        tgt_name = TARGET_NAMES.get(target, f'RT{target}')
        action = f'[LJMP] {cond_name} -> {tgt_name}'
    elif typ == 3:  # LCALL
        cond = (operand >> 4) & 7
        target = operand & 0xF
        cond_name = COND_NAMES.get(cond, f'C{cond}')
        tgt_name = TARGET_NAMES.get(target, f'RT{target}')
        action = f'[LCALL] {cond_name} -> {tgt_name}'
    elif typ == 4:  # SPECIAL
        spec_name = SPEC_NAMES.get(operand, f'SP{operand}')
        action = f'[SPECIAL] {spec_name}'
    elif typ == 5:  # RETURN
        flags = []
        if operand & 1:
            flags.append('CF1')
        if operand & 4:
            flags.append('CCOF')
        flag_str = ' ' + '+'.join(flags) if flags else ''
        action = f'[RETURN]{flag_str}'
    elif typ == 6:  # TERMINAL
        term_name = 'RNI' if (operand & 1) else 'NXT'
        action = f'[TERMINAL] {term_name}'
    elif typ == 7:  # MOVE
        action = '[MOVE]'
    else:
        action = f'[UNKNOWN TYPE {typ}]'

    return f'{src_name} -> {dst_name}  {action}{f_str}'


def decode_rom(filepath):
    """Decode the ROM binary and return list of (routine_name, instructions)."""
    with open(filepath, 'rb') as f:
        data = f.read()

    # Parse header
    magic = data[0:4]
    assert magic == b'UROM', f'Invalid magic: {magic!r}'
    version = data[4]
    num_routines = data[5]

    offset = 6
    routines = []

    for _ in range(num_routines):
        routine_id = data[offset]
        inst_count = data[offset + 1]
        offset += 2

        # Calculate bitstream size
        total_bits = inst_count * 21
        total_bytes = (total_bits + 7) // 8

        bitstream = data[offset:offset + total_bytes]
        offset += total_bytes

        # Decode each instruction
        instructions = []
        for i in range(inst_count):
            bit_offset = i * 21
            inst_val = extract_bits(bitstream, bit_offset, 21)
            fields = decode_instruction(inst_val)
            instructions.append(fields)

        routine_name = ROUTINE_NAMES.get(routine_id, f'ROUTINE_{routine_id}')
        routines.append((routine_name, instructions))

    return routines


def main():
    routines = decode_rom('/app/microcode_rom.bin')

    with open('/app/disassembly.txt', 'w') as f:
        for name, instructions in routines:
            f.write(f'=== {name} ({len(instructions)} instructions) ===\n')
            for i, (src, dst, flag, typ, operand) in enumerate(instructions):
                line = format_instruction(src, dst, flag, typ, operand)
                f.write(f'  {i}: {line}\n')
            f.write('\n')

    print(f'Disassembly written to /app/disassembly.txt')
    # Print for verification
    with open('/app/disassembly.txt') as f:
        print(f.read())


if __name__ == '__main__':
    main()
