#!/usr/bin/env python3
"""
MiniStack-16 Peephole Optimizer.
Applies semantics-preserving transformations to reduce binary size.
Handles jump targets correctly — never optimizes across basic block boundaries.
Recomputes branch offsets after instruction removal.
"""
import sys
import struct

BRANCH_OPS = {0x15, 0x16, 0x17, 0x18}  # JMP, JZ, JNZ, CALL
OPERAND_OPS = {0x01} | BRANCH_OPS       # PUSH + branches


def disassemble(binary):
    """Parse binary into instruction list and jump target set."""
    instructions = []
    jump_targets = set()
    pc = 0
    while pc < len(binary):
        addr = pc
        opcode = binary[pc]
        pc += 1

        if opcode == 0x01:  # PUSH
            if pc + 2 > len(binary):
                break
            val = struct.unpack_from('<h', binary, pc)[0]
            pc += 2
            instructions.append({'addr': addr, 'op': opcode, 'val': val})
        elif opcode in BRANCH_OPS:
            if pc + 2 > len(binary):
                break
            offset = struct.unpack_from('<h', binary, pc)[0]
            pc += 2
            target = (pc + offset) & 0xFFFF
            jump_targets.add(target)
            instructions.append({'addr': addr, 'op': opcode, 'target': target})
        else:
            instructions.append({'addr': addr, 'op': opcode})

        if opcode == 0xFF:  # HALT
            break

    return instructions, jump_targets


def is_target(instr, jump_targets):
    """Check if an instruction's original address is a jump target."""
    return instr['addr'] in jump_targets


def to_i16(val):
    """Truncate to signed 16-bit."""
    val = val & 0xFFFF
    if val >= 0x8000:
        val -= 0x10000
    return val


def apply_peephole(instructions, jump_targets):
    """Apply peephole optimization patterns until no more changes."""
    changed = True
    while changed:
        changed = False
        result = []
        i = 0
        while i < len(instructions):
            # ---- Pattern 1: PUSH X / PUSH Y / binop -> PUSH result ----
            # (constant folding for ADD, SUB, MUL)
            if (i + 2 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i + 1]['op'] == 0x01
                    and instructions[i + 2]['op'] in (0x06, 0x07, 0x08)
                    and not is_target(instructions[i + 1], jump_targets)
                    and not is_target(instructions[i + 2], jump_targets)):
                x = instructions[i]['val']
                y = instructions[i + 1]['val']
                op = instructions[i + 2]['op']
                if op == 0x06:    # ADD
                    v = x + y
                elif op == 0x07:  # SUB
                    v = x - y
                else:             # MUL
                    v = x * y
                result.append({
                    'addr': instructions[i]['addr'],
                    'op': 0x01,
                    'val': to_i16(v),
                })
                i += 3
                changed = True
                continue

            # ---- Pattern 2: PUSH 0 / ADD -> remove (identity) ----
            if (i + 1 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i]['val'] == 0
                    and instructions[i + 1]['op'] == 0x06
                    and not is_target(instructions[i], jump_targets)
                    and not is_target(instructions[i + 1], jump_targets)):
                i += 2
                changed = True
                continue

            # ---- Pattern 3: PUSH 1 / MUL -> remove (identity) ----
            if (i + 1 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i]['val'] == 1
                    and instructions[i + 1]['op'] == 0x08
                    and not is_target(instructions[i], jump_targets)
                    and not is_target(instructions[i + 1], jump_targets)):
                i += 2
                changed = True
                continue

            # ---- Pattern 4: PUSH X / POP -> remove (dead code) ----
            if (i + 1 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i + 1]['op'] == 0x02
                    and not is_target(instructions[i], jump_targets)
                    and not is_target(instructions[i + 1], jump_targets)):
                i += 2
                changed = True
                continue

            # ---- Pattern 5: PUSH X / NEG -> PUSH (-X) ----
            if (i + 1 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i + 1]['op'] == 0x0F
                    and not is_target(instructions[i + 1], jump_targets)):
                x = instructions[i]['val']
                result.append({
                    'addr': instructions[i]['addr'],
                    'op': 0x01,
                    'val': to_i16(-x),
                })
                i += 2
                changed = True
                continue

            # ---- Pattern 6: PUSH X / NOT -> PUSH (~X) ----
            if (i + 1 < len(instructions)
                    and instructions[i]['op'] == 0x01
                    and instructions[i + 1]['op'] == 0x0E
                    and not is_target(instructions[i + 1], jump_targets)):
                x = instructions[i]['val']
                result.append({
                    'addr': instructions[i]['addr'],
                    'op': 0x01,
                    'val': to_i16(~x),
                })
                i += 2
                changed = True
                continue

            result.append(instructions[i])
            i += 1

        instructions = result

    return instructions


def reassemble(instructions):
    """Convert optimized instruction list back to binary, recomputing offsets."""
    # Build old-address to new-address mapping
    old_to_new = {}
    new_addr = 0
    for instr in instructions:
        old_to_new[instr['addr']] = new_addr
        new_addr += 3 if instr['op'] in OPERAND_OPS else 1

    # Emit bytes
    output = bytearray()
    for instr in instructions:
        output.append(instr['op'])
        if instr['op'] == 0x01:  # PUSH
            output.extend(struct.pack('<h', instr['val']))
        elif instr['op'] in BRANCH_OPS:
            old_target = instr['target']
            new_src = old_to_new[instr['addr']]
            if old_target in old_to_new:
                new_target = old_to_new[old_target]
            else:
                # Target outside known instructions; preserve original offset
                new_target = old_target
            new_offset = new_target - (new_src + 3)
            output.extend(struct.pack('<h', new_offset))

    return bytes(output)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.bin> <output.bin>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'rb') as f:
        binary = f.read()

    instructions, jump_targets = disassemble(binary)
    optimized = apply_peephole(instructions, jump_targets)
    output = reassemble(optimized)

    with open(sys.argv[2], 'wb') as f:
        f.write(output)

    saved = len(binary) - len(output)
    print(f"Optimized: {len(binary)} -> {len(output)} bytes (saved {saved})")


if __name__ == '__main__':
    main()
