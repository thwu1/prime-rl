#!/usr/bin/env python3
"""
MiniStack-16 Disassembler
Converts MiniStack-16 binary bytecode back to assembly source.
Resolves jump/branch target offsets to labels.
"""
import sys
import struct

OPCODE_NAMES = {
    0x01: 'PUSH', 0x02: 'POP', 0x03: 'DUP', 0x04: 'SWAP', 0x05: 'OVER',
    0x06: 'ADD', 0x07: 'SUB', 0x08: 'MUL', 0x09: 'DIV', 0x0A: 'MOD',
    0x0B: 'AND', 0x0C: 'OR', 0x0D: 'XOR', 0x0E: 'NOT', 0x0F: 'NEG',
    0x10: 'SHL', 0x11: 'SHR', 0x12: 'EQ', 0x13: 'LT', 0x14: 'GT',
    0x15: 'JMP', 0x16: 'JZ', 0x17: 'JNZ', 0x18: 'CALL', 0x19: 'RET',
    0x1A: 'LOAD', 0x1B: 'STORE', 0x1C: 'LOADB', 0x1D: 'STOREB',
    0x1E: 'PUTC', 0x1F: 'PUTI', 0x20: 'GETC', 0xFF: 'HALT',
}

BRANCH_OPS = {0x15, 0x16, 0x17, 0x18}  # JMP, JZ, JNZ, CALL
OPERAND_OPS = {0x01} | BRANCH_OPS       # PUSH + branches


def disassemble(binary):
    """Disassemble binary bytecode to a list of (addr, mnemonic, operand) tuples.
    Also returns a set of addresses that are jump targets (for label generation).
    """
    instructions = []
    jump_targets = set()
    pc = 0

    while pc < len(binary):
        addr = pc
        opcode = binary[pc]
        pc += 1

        if opcode not in OPCODE_NAMES:
            raise ValueError(f"Unknown opcode 0x{opcode:02X} at address 0x{addr:04X}")

        mnemonic = OPCODE_NAMES[opcode]

        if opcode == 0x01:  # PUSH
            if pc + 2 > len(binary):
                raise ValueError(f"Truncated PUSH operand at 0x{addr:04X}")
            val = struct.unpack_from('<h', binary, pc)[0]
            pc += 2
            instructions.append((addr, mnemonic, ('imm', val)))

        elif opcode in BRANCH_OPS:
            if pc + 2 > len(binary):
                raise ValueError(f"Truncated branch operand at 0x{addr:04X}")
            offset = struct.unpack_from('<h', binary, pc)[0]
            pc += 2
            # Offset is relative to the address AFTER this instruction
            target = (pc + offset) & 0xFFFF
            jump_targets.add(target)
            instructions.append((addr, mnemonic, ('target', target)))

        else:
            instructions.append((addr, mnemonic, None))

        if opcode == 0xFF:  # HALT
            break

    return instructions, jump_targets


def format_assembly(instructions, jump_targets):
    """Format disassembled instructions as assembly source text."""
    # Generate label names for jump targets
    labels = {}
    label_counter = 0
    for target in sorted(jump_targets):
        labels[target] = f"label_{label_counter}"
        label_counter += 1

    lines = []
    for addr, mnemonic, operand in instructions:
        # Emit label if this address is a jump target
        if addr in labels:
            lines.append(f"{labels[addr]}:")

        # Format instruction
        if operand is None:
            lines.append(f"    {mnemonic.lower()}")
        elif operand[0] == 'imm':
            lines.append(f"    {mnemonic.lower()} {operand[1]}")
        elif operand[0] == 'target':
            target_addr = operand[1]
            if target_addr in labels:
                lines.append(f"    {mnemonic.lower()} {labels[target_addr]}")
            else:
                # Target beyond disassembled range; use numeric offset
                offset = target_addr - (addr + 3)
                lines.append(f"    {mnemonic.lower()} {offset}")

    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.bin> <output.asm>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'rb') as f:
        binary = f.read()

    instructions, jump_targets = disassemble(binary)
    asm_text = format_assembly(instructions, jump_targets)

    with open(sys.argv[2], 'w') as f:
        f.write(asm_text)

    print(f"Disassembled {len(binary)} bytes -> {sys.argv[2]} "
          f"({len(instructions)} instructions, {len(jump_targets)} labels)")


if __name__ == '__main__':
    main()
