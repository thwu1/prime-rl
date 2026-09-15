#!/usr/bin/env python3
"""
MiniStack-16 Assembler
Assembles MiniStack-16 assembly source into binary bytecode.
See spec.md for the instruction set specification.
"""
import sys
import struct
import re

OPCODES = {
    'PUSH': 0x01, 'POP': 0x02, 'DUP': 0x03, 'SWAP': 0x04, 'OVER': 0x05,
    'ADD': 0x06, 'SUB': 0x07, 'MUL': 0x08, 'DIV': 0x09, 'MOD': 0x0A,
    'AND': 0x0B, 'OR': 0x0C, 'XOR': 0x0D, 'NOT': 0x0E, 'NEG': 0x0F,
    'SHL': 0x10, 'SHR': 0x11, 'EQ': 0x12, 'LT': 0x13, 'GT': 0x14,
    'JMP': 0x15, 'JZ': 0x16, 'JNZ': 0x17, 'CALL': 0x18, 'RET': 0x19,
    'LOAD': 0x1A, 'STORE': 0x1B, 'LOADB': 0x1C, 'STOREB': 0x1D,
    'PUTC': 0x1E, 'PUTI': 0x1F, 'GETC': 0x20, 'HALT': 0xFF,
}

# Instructions that take a 16-bit operand (3 bytes total)
BRANCH_OPS = {'JMP', 'JZ', 'JNZ', 'CALL'}
OPERAND_OPS = {'PUSH'} | BRANCH_OPS


def parse_int(s):
    """Parse an integer literal (decimal or 0x hex)."""
    s = s.strip()
    neg = False
    if s.startswith('-'):
        neg = True
        s = s[1:]
    if s.startswith('0x') or s.startswith('0X'):
        val = int(s, 16)
    else:
        val = int(s)
    return -val if neg else val


def assemble(source_text):
    """Two-pass assembler: first pass collects labels, second pass emits code."""
    lines = source_text.split('\n')

    # --- Pass 1: collect labels and calculate instruction addresses ---
    instructions = []
    labels = {}
    addr = 0

    for line_num, raw_line in enumerate(lines, 1):
        # Strip comments
        line = re.sub(r'[;#].*', '', raw_line).strip()
        if not line:
            continue

        # Label definition
        if line.endswith(':'):
            label_name = line[:-1].strip()
            if label_name in labels:
                print(f"Error line {line_num}: duplicate label '{label_name}'",
                      file=sys.stderr)
                sys.exit(1)
            labels[label_name] = addr
            continue

        # Parse mnemonic and optional operand
        parts = line.split(None, 1)
        mnemonic = parts[0].upper()
        operand_str = parts[1].strip() if len(parts) > 1 else None

        if mnemonic not in OPCODES:
            print(f"Error line {line_num}: unknown instruction '{mnemonic}'",
                  file=sys.stderr)
            sys.exit(1)

        instructions.append((addr, mnemonic, operand_str, line_num))
        addr += 3 if mnemonic in OPERAND_OPS else 1

    # --- Pass 2: encode instructions into bytes ---
    output = bytearray()

    for addr, mnemonic, operand_str, line_num in instructions:
        opcode = OPCODES[mnemonic]
        output.append(opcode)

        if mnemonic == 'PUSH':
            if operand_str is None:
                print(f"Error line {line_num}: PUSH requires an operand",
                      file=sys.stderr)
                sys.exit(1)
            val = parse_int(operand_str)
            # Convert to unsigned 16-bit representation
            if val < 0:
                val = val & 0xFF
            else:
                val = val & 0xFFFF
            output.extend(struct.pack('<H', val))

        elif mnemonic in BRANCH_OPS:
            if operand_str is None:
                print(f"Error line {line_num}: {mnemonic} requires a target",
                      file=sys.stderr)
                sys.exit(1)

            if operand_str.strip() in labels:
                target_addr = labels[operand_str.strip()]
                # Offset relative to the current instruction address
                offset = target_addr - addr
                output.extend(struct.pack('<h', offset))
            else:
                # Numeric offset provided directly
                val = parse_int(operand_str)
                output.extend(struct.pack('<h', val))

    return bytes(output)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.asm> <output.bin>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        source = f.read()

    binary = assemble(source)

    with open(sys.argv[2], 'wb') as f:
        f.write(binary)

    print(f"Assembled {len(binary)} bytes -> {sys.argv[2]}")


if __name__ == '__main__':
    main()
