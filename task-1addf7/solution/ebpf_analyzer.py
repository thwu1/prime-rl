#!/usr/bin/env python3
"""
eBPF Bytecode Static Analyzer

Reads raw eBPF program bytecode, constructs control flow graphs,
and performs static verification checks modeled after the Linux
kernel's eBPF verifier.
"""

import json
import os
import struct
from collections import defaultdict

# ============================================================
# eBPF opcode constants
# ============================================================

# Combined opcodes for load/store
OP_LD_IMM64 = 0x18       # BPF_LD | BPF_IMM | BPF_DW (16-byte instruction)
OP_LDX_W    = 0x61       # BPF_LDX | BPF_MEM | BPF_W
OP_LDX_H    = 0x69       # BPF_LDX | BPF_MEM | BPF_H
OP_LDX_B    = 0x71       # BPF_LDX | BPF_MEM | BPF_B
OP_LDX_DW   = 0x79       # BPF_LDX | BPF_MEM | BPF_DW
OP_ST_W     = 0x62       # BPF_ST  | BPF_MEM | BPF_W
OP_ST_H     = 0x6a       # BPF_ST  | BPF_MEM | BPF_H
OP_ST_B     = 0x72       # BPF_ST  | BPF_MEM | BPF_B
OP_ST_DW    = 0x7a       # BPF_ST  | BPF_MEM | BPF_DW
OP_STX_W    = 0x63       # BPF_STX | BPF_MEM | BPF_W
OP_STX_H    = 0x6b       # BPF_STX | BPF_MEM | BPF_H
OP_STX_B    = 0x73       # BPF_STX | BPF_MEM | BPF_B
OP_STX_DW   = 0x7b       # BPF_STX | BPF_MEM | BPF_DW

# ALU64 opcodes
OP_ALU64_ADD_K  = 0x07   # BPF_ALU64 | BPF_ADD | BPF_K
OP_ALU64_ADD_X  = 0x0f   # BPF_ALU64 | BPF_ADD | BPF_X
OP_ALU64_MOV_K  = 0xb7   # BPF_ALU64 | BPF_MOV | BPF_K
OP_ALU64_MOV_X  = 0xbf   # BPF_ALU64 | BPF_MOV | BPF_X

# JMP opcodes
OP_JMP_JA     = 0x05     # BPF_JMP | BPF_JA
OP_JMP_JEQ_K  = 0x15     # BPF_JMP | BPF_JEQ | BPF_K
OP_JMP_JEQ_X  = 0x1d     # BPF_JMP | BPF_JEQ | BPF_X
OP_JMP_JGT_K  = 0x25     # BPF_JMP | BPF_JGT | BPF_K
OP_JMP_JGT_X  = 0x2d     # BPF_JMP | BPF_JGT | BPF_X
OP_JMP_JGE_K  = 0x35     # BPF_JMP | BPF_JGE | BPF_K
OP_JMP_JGE_X  = 0x3d     # BPF_JMP | BPF_JGE | BPF_X
OP_JMP_JNE_K  = 0x55     # BPF_JMP | BPF_JNE | BPF_K
OP_JMP_JNE_X  = 0x5d     # BPF_JMP | BPF_JNE | BPF_X
OP_JMP_JSGT_K = 0x65     # BPF_JMP | BPF_JSGT | BPF_K
OP_JMP_JSGT_X = 0x6d     # BPF_JMP | BPF_JSGT | BPF_X
OP_JMP_JSGE_K = 0x75     # BPF_JMP | BPF_JSGE | BPF_K
OP_JMP_JSGE_X = 0x7d     # BPF_JMP | BPF_JSGE | BPF_X
OP_JMP_JLT_K  = 0xa5     # BPF_JMP | BPF_JLT | BPF_K
OP_JMP_JLT_X  = 0xad     # BPF_JMP | BPF_JLT | BPF_X
OP_JMP_JLE_K  = 0xb5     # BPF_JMP | BPF_JLE | BPF_K
OP_JMP_JLE_X  = 0xbd     # BPF_JMP | BPF_JLE | BPF_X
OP_JMP_JSLT_K = 0xc5     # BPF_JMP | BPF_JSLT | BPF_K
OP_JMP_JSLT_X = 0xcd     # BPF_JMP | BPF_JSLT | BPF_X
OP_JMP_JSLE_K = 0xd5     # BPF_JMP | BPF_JSLE | BPF_K
OP_JMP_JSLE_X = 0xdd     # BPF_JMP | BPF_JSLE | BPF_X
OP_JMP_CALL   = 0x85     # BPF_JMP | BPF_CALL
OP_JMP_EXIT   = 0x95     # BPF_JMP | BPF_EXIT

# Opcode sets
LDX_OPCODES = {OP_LDX_W, OP_LDX_H, OP_LDX_B, OP_LDX_DW}
ST_OPCODES  = {OP_ST_W, OP_ST_H, OP_ST_B, OP_ST_DW}
STX_OPCODES = {OP_STX_W, OP_STX_H, OP_STX_B, OP_STX_DW}
STORE_OPCODES = ST_OPCODES | STX_OPCODES

CONDITIONAL_JMP_OPCODES = {
    OP_JMP_JEQ_K, OP_JMP_JEQ_X, OP_JMP_JGT_K, OP_JMP_JGT_X,
    OP_JMP_JGE_K, OP_JMP_JGE_X, OP_JMP_JNE_K, OP_JMP_JNE_X,
    OP_JMP_JSGT_K, OP_JMP_JSGT_X, OP_JMP_JSGE_K, OP_JMP_JSGE_X,
    OP_JMP_JLT_K, OP_JMP_JLT_X, OP_JMP_JLE_K, OP_JMP_JLE_X,
    OP_JMP_JSLT_K, OP_JMP_JSLT_X, OP_JMP_JSLE_K, OP_JMP_JSLE_X,
}

# BPF helper function IDs
HELPER_MAP_LOOKUP_ELEM = 1

# BPF_X source bit in opcode byte (bit 3)
BPF_X = 0x08

# Register type constants for abstract interpretation
REG_UNKNOWN       = 'UNKNOWN'
REG_SCALAR        = 'SCALAR'
REG_CTX           = 'CTX'
REG_FP            = 'FP'
REG_PKT_DATA      = 'PKT_DATA'
REG_PKT_END       = 'PKT_END'
REG_PKT_DATA_PLUS = 'PKT_DATA_PLUS'


# ============================================================
# Instruction decoding
# ============================================================

def decode_instructions(bytecode):
    """Decode raw eBPF bytecode into a list of instruction dicts."""
    instructions = []
    offset = 0
    while offset < len(bytecode):
        code, regs, off, imm = struct.unpack_from('<BBhi', bytecode, offset)
        dst = regs & 0x0f
        src = (regs >> 4) & 0x0f
        insn = {
            'idx': len(instructions),
            'code': code,
            'dst': dst,
            'src': src,
            'off': off,
            'imm': imm,
            'is_continuation': False,
        }
        instructions.append(insn)
        offset += 8

        # LD_IMM64 is a 16-byte instruction spanning two slots
        if code == OP_LD_IMM64:
            code2, regs2, off2, imm2 = struct.unpack_from('<BBhi', bytecode, offset)
            cont = {
                'idx': len(instructions),
                'code': code2,
                'dst': regs2 & 0x0f,
                'src': (regs2 >> 4) & 0x0f,
                'off': off2,
                'imm': imm2,
                'is_continuation': True,
            }
            instructions.append(cont)
            offset += 8

    return instructions


# ============================================================
# Control flow graph
# ============================================================

def build_cfg(instructions):
    """Build CFG as adjacency list: {insn_idx: [successor_indices]}."""
    n = len(instructions)
    cfg = {}

    for insn in instructions:
        idx = insn['idx']
        code = insn['code']

        if insn['is_continuation']:
            cfg[idx] = [idx + 1] if idx + 1 < n else []
        elif code == OP_JMP_EXIT:
            cfg[idx] = []
        elif code == OP_JMP_JA:
            target = idx + 1 + insn['off']
            cfg[idx] = [target]
        elif code in CONDITIONAL_JMP_OPCODES:
            fall_through = idx + 1
            target = idx + 1 + insn['off']
            cfg[idx] = [fall_through, target]
        elif code == OP_LD_IMM64:
            cfg[idx] = [idx + 1]
        else:
            cfg[idx] = [idx + 1] if idx + 1 < n else []

    return cfg


def find_reachable(cfg, entry=0):
    """BFS from entry to find all reachable instruction indices."""
    reachable = set()
    queue = [entry]
    while queue:
        node = queue.pop(0)
        if node in reachable:
            continue
        reachable.add(node)
        for succ in cfg.get(node, []):
            if succ not in reachable:
                queue.append(succ)
    return reachable


# ============================================================
# Verification checks
# ============================================================

def check_unreachable(instructions, cfg, reachable):
    """Detect instructions not reachable from entry point."""
    findings = []
    for insn in instructions:
        if insn['idx'] not in reachable and not insn['is_continuation']:
            findings.append({
                'type': 'unreachable_code',
                'instruction': insn['idx'],
            })
    return findings


def check_stack_oob(instructions, reachable):
    """Detect memory accesses through R10 with offset below -512."""
    findings = []
    for insn in instructions:
        if insn['idx'] not in reachable:
            continue
        code = insn['code']

        # LDX: base register is 'src'
        if code in LDX_OPCODES and insn['src'] == 10 and insn['off'] < -512:
            findings.append({
                'type': 'stack_out_of_bounds',
                'instruction': insn['idx'],
            })

        # ST/STX: base register is 'dst'
        if code in STORE_OPCODES and insn['dst'] == 10 and insn['off'] < -512:
            findings.append({
                'type': 'stack_out_of_bounds',
                'instruction': insn['idx'],
            })

    return findings


def check_null_deref(instructions, cfg, reachable):
    """Detect dereference of bpf_map_lookup_elem return without null check.

    After call #1 (bpf_map_lookup_elem), R0 holds PTR_TO_MAP_VALUE_OR_NULL.
    If R0 is used as a base in LDX before a conditional compare of R0 against 0,
    that's a null pointer dereference.
    """
    findings = []

    for insn in instructions:
        if insn['idx'] not in reachable:
            continue
        if insn['code'] != OP_JMP_CALL or insn['imm'] != HELPER_MAP_LOOKUP_ELEM:
            continue

        call_idx = insn['idx']

        # Walk forward linearly from the call
        for fwd_idx in range(call_idx + 1, len(instructions)):
            if fwd_idx not in reachable:
                continue
            fwd = instructions[fwd_idx]
            code = fwd['code']

            # Skip continuation slots
            if fwd['is_continuation']:
                continue

            # Null check: conditional jump comparing R0 to 0
            if code in (OP_JMP_JEQ_K, OP_JMP_JNE_K) and fwd['dst'] == 0 and fwd['imm'] == 0:
                break  # Null check found, safe

            # Dereference: LDX with R0 as base register (src field)
            if code in LDX_OPCODES and fwd['src'] == 0:
                findings.append({
                    'type': 'null_ptr_deref',
                    'instruction': fwd_idx,
                })
                break

            # R0 overwritten by MOV or another CALL: stop tracking
            if code == OP_ALU64_MOV_K and fwd['dst'] == 0:
                break
            if code == OP_ALU64_MOV_X and fwd['dst'] == 0:
                break
            if code == OP_JMP_CALL:
                break
            if code == OP_LD_IMM64 and fwd['dst'] == 0:
                break

    return findings


def check_packet_bounds(instructions, cfg, reachable, prog_type):
    """Detect packet data access without prior bounds check in XDP programs.

    In XDP programs, R1 is the xdp_md context pointer at entry.
    Loading from ctx+0 yields a PKT_DATA pointer.
    Loading from ctx+4 yields a PKT_END pointer.
    Before dereferencing a PKT_DATA-derived pointer, there must be a comparison
    of (data_ptr + offset) against data_end with a conditional jump.
    """
    if prog_type != 'xdp':
        return []

    findings = []

    # Initialize register type state
    reg_types = {i: REG_UNKNOWN for i in range(11)}
    reg_types[1] = REG_CTX   # R1 = xdp_md context at XDP entry
    reg_types[10] = REG_FP   # R10 = frame pointer (always)
    bounds_checked = False

    for insn in instructions:
        idx = insn['idx']
        if idx not in reachable:
            continue
        if insn['is_continuation']:
            continue

        code = insn['code']

        # --- Register type tracking ---

        if code == OP_ALU64_MOV_X:  # dst = src
            reg_types[insn['dst']] = reg_types.get(insn['src'], REG_UNKNOWN)

        elif code == OP_ALU64_MOV_K:  # dst = imm
            reg_types[insn['dst']] = REG_SCALAR

        elif code in (OP_ALU64_ADD_K, OP_ALU64_ADD_X):  # dst += imm or dst += src
            if reg_types.get(insn['dst']) in (REG_PKT_DATA, REG_PKT_DATA_PLUS):
                reg_types[insn['dst']] = REG_PKT_DATA_PLUS

        elif code == OP_LD_IMM64:  # 64-bit immediate load
            reg_types[insn['dst']] = REG_SCALAR

        elif code in LDX_OPCODES:
            src_type = reg_types.get(insn['src'], REG_UNKNOWN)

            if src_type == REG_CTX:
                # Loading from the XDP context structure
                if insn['off'] == 0:
                    reg_types[insn['dst']] = REG_PKT_DATA
                elif insn['off'] == 4:
                    reg_types[insn['dst']] = REG_PKT_END
                else:
                    reg_types[insn['dst']] = REG_SCALAR
            elif src_type in (REG_PKT_DATA, REG_PKT_DATA_PLUS):
                # Dereferencing packet data pointer
                if not bounds_checked:
                    findings.append({
                        'type': 'packet_bounds',
                        'instruction': idx,
                    })
                reg_types[insn['dst']] = REG_SCALAR
            else:
                reg_types[insn['dst']] = REG_UNKNOWN

        elif code in CONDITIONAL_JMP_OPCODES:
            # Check if this is a bounds comparison between packet data and data_end
            dst_type = reg_types.get(insn['dst'], REG_UNKNOWN)
            if code & BPF_X:  # Register source
                src_type = reg_types.get(insn['src'], REG_UNKNOWN)
            else:
                src_type = REG_SCALAR

            pkt_types = (REG_PKT_DATA, REG_PKT_DATA_PLUS)
            if (dst_type in pkt_types and src_type == REG_PKT_END) or \
               (src_type in pkt_types and dst_type == REG_PKT_END):
                bounds_checked = True

        elif code == OP_JMP_CALL:
            # Helper calls clobber R0-R5
            for r in range(6):
                reg_types[r] = REG_UNKNOWN

    return findings


# ============================================================
# Main analysis driver
# ============================================================

def analyze_program(name, bytecode, metadata):
    """Analyze a single eBPF program and return results dict."""
    instructions = decode_instructions(bytecode)
    cfg = build_cfg(instructions)
    reachable = find_reachable(cfg)

    findings = []
    findings.extend(check_unreachable(instructions, cfg, reachable))
    findings.extend(check_stack_oob(instructions, reachable))
    findings.extend(check_null_deref(instructions, cfg, reachable))
    findings.extend(check_packet_bounds(
        instructions, cfg, reachable, metadata.get('type', '')
    ))

    # Sort findings by instruction index, then by type for determinism
    findings.sort(key=lambda f: (f['instruction'], f['type']))

    return {
        'program': name,
        'num_instructions': len(instructions),
        'cfg': {str(k): v for k, v in sorted(cfg.items())},
        'findings': findings,
    }


def main():
    with open('/app/metadata.json') as f:
        metadata = json.load(f)

    os.makedirs('/app/results', exist_ok=True)

    for name, prog_meta in metadata['programs'].items():
        prog_path = os.path.join('/app/programs', prog_meta['file'])
        with open(prog_path, 'rb') as f:
            bytecode = f.read()

        result = analyze_program(name, bytecode, prog_meta)

        result_path = os.path.join('/app/results', f'{name}.json')
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"Analyzed {name}: {len(result['findings'])} finding(s)")


if __name__ == '__main__':
    main()
