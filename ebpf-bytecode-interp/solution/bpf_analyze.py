#!/usr/bin/env python3
"""Static analysis of BPF bytecode: CFG, stack depth, register usage."""
import json
import struct
import sys

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1


def decode(raw):
    """Decode BPF bytecode into a dict of slot -> instruction info."""
    insns = {}
    i = 0
    while i < len(raw):
        if i + 8 > len(raw):
            break
        opcode, regs, off, imm = struct.unpack_from('<BBhi', raw, i)
        slot = i // 8
        dst = regs & 0x0f
        src = (regs >> 4) & 0x0f
        cls = opcode & 0x07
        is_wide = False
        if cls == 0x00 and ((opcode >> 5) & 7) == 0 and ((opcode >> 3) & 3) == 3:
            is_wide = True
        insns[slot] = {
            'opcode': opcode, 'dst': dst, 'src': src,
            'off': off, 'imm': imm, 'cls': cls, 'wide': is_wide,
        }
        i += 16 if is_wide else 8
    return insns


def analyze(hex_bytecode):
    raw = bytes.fromhex(hex_bytecode)
    insns = decode(raw)
    slots = sorted(insns.keys())

    logical_count = len(insns)
    regs_written = set()
    max_stack = 0

    # Pass 1: register writes, stack depth, block boundary candidates
    block_starts = {0}

    for slot in slots:
        ins = insns[slot]
        opcode, dst, src, off, cls = (
            ins['opcode'], ins['dst'], ins['src'], ins['off'], ins['cls'])
        code = (opcode >> 4) & 0x0f

        # Register writes
        if ins['wide']:
            regs_written.add(dst)
        elif cls in (0x04, 0x07):  # ALU / ALU64
            regs_written.add(dst)
        elif cls == 0x01:  # LDX
            regs_written.add(dst)

        # Stack depth (via R10 offsets)
        if cls == 0x01 and src == 10 and off < 0:  # LDX from stack
            max_stack = max(max_stack, -off)
        if cls == 0x02 and dst == 10 and off < 0:  # ST to stack
            max_stack = max(max_stack, -off)
        if cls == 0x03 and dst == 10 and off < 0:  # STX to stack
            max_stack = max(max_stack, -off)

        # Basic block boundaries from jumps
        if cls == 0x05:  # JMP
            if code == 0x0:  # JA
                target = slot + off + 1
                block_starts.add(target)
                next_s = slot + 1
                block_starts.add(next_s)
            elif code == 0x9:  # EXIT
                next_s = slot + 1
                block_starts.add(next_s)
            elif code == 0x8:  # CALL
                next_s = slot + 1
                block_starts.add(next_s)
            else:  # conditional branch
                target = slot + off + 1
                block_starts.add(target)
                block_starts.add(slot + 1)
        elif cls == 0x06:  # JMP32
            if code == 0x0:
                target = slot + ins['imm'] + 1
                block_starts.add(target)
                block_starts.add(slot + 1)
            else:
                target = slot + off + 1
                block_starts.add(target)
                block_starts.add(slot + 1)

    # Filter block starts to valid instruction slots
    block_starts = sorted(s for s in block_starts if s in insns)

    # Build CFG edges
    edges = []
    has_back = False

    for i, bb_start in enumerate(block_starts):
        # Find last instruction slot in this block
        if i + 1 < len(block_starts):
            bb_end_limit = block_starts[i + 1]
        else:
            bb_end_limit = max(slots) + 1
        block_slots = [s for s in slots if bb_start <= s < bb_end_limit]
        if not block_slots:
            continue
        last_slot = block_slots[-1]
        ins = insns[last_slot]
        opcode, cls = ins['opcode'], ins['cls']
        code = (opcode >> 4) & 0x0f
        off = ins['off']

        if cls == 0x05:  # JMP
            if code == 0x0:  # JA
                target = last_slot + off + 1
                if target in block_starts:
                    edges.append([bb_start, target])
                    if target <= bb_start:
                        has_back = True
            elif code == 0x9:  # EXIT
                pass
            elif code == 0x8:  # CALL
                fall = last_slot + 1
                if fall in block_starts:
                    edges.append([bb_start, fall])
            else:  # conditional
                fall = last_slot + 1
                if fall in block_starts:
                    edges.append([bb_start, fall])
                target = last_slot + off + 1
                if target in block_starts:
                    edges.append([bb_start, target])
                    if target <= bb_start:
                        has_back = True
        elif cls == 0x06:  # JMP32
            if code == 0x0:
                target = last_slot + ins['imm'] + 1
                if target in block_starts:
                    edges.append([bb_start, target])
                    if target <= bb_start:
                        has_back = True
            else:
                fall = last_slot + 1
                if fall in block_starts:
                    edges.append([bb_start, fall])
                target = last_slot + off + 1
                if target in block_starts:
                    edges.append([bb_start, target])
                    if target <= bb_start:
                        has_back = True
        else:
            # Non-jump: fall through
            next_slot = last_slot + (2 if ins['wide'] else 1)
            if next_slot in block_starts:
                edges.append([bb_start, next_slot])

    result = {
        'instruction_count': logical_count,
        'basic_blocks': block_starts,
        'edges': sorted(edges),
        'has_back_edges': has_back,
        'max_stack_depth': max_stack,
        'registers_written': sorted(regs_written),
    }
    print(json.dumps(result))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: bpf_analyze <hex_bytecode>", file=sys.stderr)
        sys.exit(1)
    analyze(sys.argv[1])
