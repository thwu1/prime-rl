#!/usr/bin/env python3
"""
BPF ELF object verifier — parses BPF ELF files, extracts bytecode,
verifies safety properties, and produces disassembly via llvm-objdump-18.
"""

import json
import os
import re
import struct
import subprocess
import sys
from enum import IntEnum


# ── ELF parser ──────────────────────────────────────────────

SHT_PROGBITS = 1
SHT_STRTAB = 3
SHF_EXECINSTR = 0x4


def parse_elf(filepath):
    """Parse a BPF ELF relocatable object file."""
    with open(filepath, 'rb') as f:
        data = f.read()

    # Verify ELF magic
    if data[:4] != b'\x7fELF':
        raise ValueError(f"Not an ELF file: {filepath}")

    # ELF64 header fields
    e_shoff = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx = struct.unpack_from('<H', data, 62)[0]

    # Parse section headers
    sections = []
    for i in range(e_shnum):
        base = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from('<I', data, base)[0]
        sh_type = struct.unpack_from('<I', data, base + 4)[0]
        sh_flags = struct.unpack_from('<Q', data, base + 8)[0]
        sh_offset = struct.unpack_from('<Q', data, base + 24)[0]
        sh_size = struct.unpack_from('<Q', data, base + 32)[0]
        sections.append({
            'name_off': sh_name, 'type': sh_type, 'flags': sh_flags,
            'offset': sh_offset, 'size': sh_size,
        })

    # Resolve section names from .shstrtab
    strtab = sections[e_shstrndx]
    strtab_data = data[strtab['offset']:strtab['offset'] + strtab['size']]

    def get_name(off):
        end = strtab_data.index(b'\x00', off)
        return strtab_data[off:end].decode('ascii')

    named = {}
    for s in sections:
        name = get_name(s['name_off'])
        if name:
            named[name] = s

    # Extract .text (BPF bytecode)
    text_sec = named['.text']
    text_data = data[text_sec['offset']:text_sec['offset'] + text_sec['size']]

    # Extract .bpf_meta (program type)
    meta_sec = named['.bpf_meta']
    prog_type_id = data[meta_sec['offset']]

    # Extract .maps (if present)
    maps_data = b""
    if '.maps' in named:
        maps_sec = named['.maps']
        maps_data = data[maps_sec['offset']:maps_sec['offset'] + maps_sec['size']]

    # Parse program type
    prog_type = {1: "xdp", 2: "kprobe", 3: "tracepoint"}.get(prog_type_id, "unknown")

    # Parse map descriptors
    maps = []
    for i in range(0, len(maps_data), 16):
        map_id, map_type, key_size, value_size = struct.unpack_from('<IIII', maps_data, i)
        maps.append({"id": map_id, "type": map_type,
                      "key_size": key_size, "value_size": value_size})

    # Parse BPF instructions
    instructions = []
    for i in range(0, len(text_data), 8):
        opcode, regs, off, imm = struct.unpack_from('<BBhi', text_data, i)
        dst = regs & 0xf
        src = (regs >> 4) & 0xf
        mnemonic = OPCODE_TO_MNEMONIC.get(opcode, f"unknown_{opcode:#x}")
        instructions.append({"op": mnemonic, "dst": dst, "src": src,
                              "off": off, "imm": imm})

    return {"prog_type": prog_type, "maps": maps, "instructions": instructions}


# ── Disassembly via llvm-objdump-18 ─────────────────────────

def get_disasm(filepath):
    """Run llvm-objdump-18 and extract instruction mnemonics."""
    result = subprocess.run(
        ["llvm-objdump-18", "-d", "--no-show-raw-insn", filepath],
        capture_output=True, text=True, timeout=10,
    )
    lines = []
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        m = re.match(r'^[0-9a-f]+:\s+(.+)$', stripped)
        if m:
            lines.append(m.group(1).strip())
    return lines


# ── BPF instruction tables ──────────────────────────────────

OPCODE_TO_MNEMONIC = {
    0xb7: "mov64_imm", 0xbf: "mov64_reg", 0xb4: "mov32_imm",
    0x07: "add64_imm", 0x0f: "add64_reg", 0x17: "sub64_imm",
    0x57: "and64_imm",
    0x61: "ldx_w", 0x69: "ldx_h", 0x71: "ldx_b", 0x79: "ldx_dw",
    0x62: "st_w", 0x7a: "st_dw",
    0x73: "stx_b", 0x63: "stx_w", 0x6b: "stx_h", 0x7b: "stx_dw",
    0x05: "ja", 0x15: "jeq_imm", 0x55: "jne_imm",
    0x2d: "jgt_reg", 0x3d: "jge_reg", 0xad: "jlt_reg", 0xbd: "jle_reg",
    0x1d: "jeq_reg", 0x5d: "jne_reg",
    0x85: "call", 0x95: "exit",
}

PROG_TYPES = {1: "xdp", 2: "kprobe", 3: "tracepoint"}


# ── Verification engine ─────────────────────────────────────

class RegType(IntEnum):
    NOT_INIT = 0
    SCALAR = 1
    PTR_TO_CTX = 2
    PTR_TO_PACKET = 3
    PTR_TO_PACKET_END = 4
    PTR_TO_MAP_VALUE = 5
    PTR_TO_MAP_VALUE_OR_NULL = 6
    PTR_TO_STACK = 7


PTR_TYPES_PRESERVED = {RegType.PTR_TO_PACKET, RegType.PTR_TO_STACK}

REG_JUMP_OPS = {
    "jgt_reg", "jge_reg", "jlt_reg", "jle_reg", "jeq_reg", "jne_reg",
}

IMM_JUMP_OPS = {"jeq_imm", "jne_imm"}

ALL_CONDITIONAL_JUMPS = REG_JUMP_OPS | IMM_JUMP_OPS


def build_cfg(instructions):
    n = len(instructions)
    succs = {}
    for i, insn in enumerate(instructions):
        op = insn["op"]
        off = insn.get("off", 0)
        if op == "exit":
            succs[i] = []
        elif op == "ja":
            succs[i] = [i + 1 + off]
        elif op in ALL_CONDITIONAL_JUMPS:
            succs[i] = [i + 1, i + 1 + off]
        else:
            succs[i] = [i + 1] if i + 1 < n else []
    return succs


def check_loops(instructions, succs):
    n = len(instructions)
    for i in range(n):
        for s in succs.get(i, []):
            if s <= i:
                return {"verdict": "reject", "reason": "loop"}
    return None


def check_reachability(instructions, succs):
    n = len(instructions)
    reachable = set()
    stack = [0]
    while stack:
        idx = stack.pop()
        if idx in reachable or idx < 0 or idx >= n:
            continue
        reachable.add(idx)
        for s in succs.get(idx, []):
            stack.append(s)
    for i in range(n):
        if i not in reachable:
            return {"verdict": "reject", "reason": "unreachable"}
    return None


def check_exit_coverage(instructions, succs):
    n = len(instructions)
    for i in range(n):
        op = instructions[i]["op"]
        s_list = succs.get(i, [])
        if op != "exit" and len(s_list) == 0:
            return {"verdict": "reject", "reason": "no_exit"}
        for s in s_list:
            if s < 0 or s >= n:
                return {"verdict": "reject", "reason": "no_exit"}
    return None


def check_instruction(insn, regs, pkt_bounds, prog_type, idx):
    op = insn["op"]
    dst = insn.get("dst", 0)
    src = insn.get("src", 0)

    if op in ("mov64_reg",):
        if regs[src] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        regs[dst] = regs[src]
        return None

    if op in ("mov64_imm", "mov32_imm"):
        regs[dst] = RegType.SCALAR
        return None

    if op in ("add64_imm", "sub64_imm", "and64_imm"):
        if regs[dst] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if regs[dst] not in PTR_TYPES_PRESERVED:
            regs[dst] = RegType.SCALAR
        return None

    if op in ("add64_reg",):
        if regs[dst] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if regs[src] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        regs[dst] = RegType.SCALAR
        return None

    if op in ("ldx_b", "ldx_h", "ldx_w", "ldx_dw"):
        off = insn.get("off", 0)
        if regs[src] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if regs[src] == RegType.PTR_TO_MAP_VALUE_OR_NULL:
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        if regs[src] in (RegType.SCALAR, RegType.PTR_TO_PACKET_END):
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        if regs[src] == RegType.PTR_TO_PACKET:
            if src not in pkt_bounds:
                return {"verdict": "reject", "reason": "pkt_bounds"}
        if regs[src] == RegType.PTR_TO_CTX and prog_type == "xdp":
            if off == 0:
                regs[dst] = RegType.PTR_TO_PACKET
            elif off == 4:
                regs[dst] = RegType.PTR_TO_PACKET_END
            else:
                regs[dst] = RegType.SCALAR
        else:
            regs[dst] = RegType.SCALAR
        return None

    if op in ("st_w", "st_dw"):
        if regs[dst] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if regs[dst] == RegType.PTR_TO_MAP_VALUE_OR_NULL:
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        if regs[dst] in (RegType.SCALAR, RegType.PTR_TO_PACKET_END):
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        return None

    if op in ("stx_b", "stx_w", "stx_dw", "stx_h"):
        if regs[dst] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if regs[dst] == RegType.PTR_TO_MAP_VALUE_OR_NULL:
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        if regs[dst] in (RegType.SCALAR, RegType.PTR_TO_PACKET_END):
            return {"verdict": "reject", "reason": "null_ptr_deref"}
        if regs[src] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        return None

    if op == "call":
        imm = insn.get("imm", 0)
        if imm == 1:
            regs[0] = RegType.PTR_TO_MAP_VALUE_OR_NULL
        else:
            regs[0] = RegType.SCALAR
        for r in range(1, 6):
            regs[r] = RegType.NOT_INIT
        return None

    if op in ALL_CONDITIONAL_JUMPS:
        if regs[dst] == RegType.NOT_INIT:
            return {"verdict": "reject", "reason": "uninit_reg"}
        if op in REG_JUMP_OPS:
            if regs[src] == RegType.NOT_INIT:
                return {"verdict": "reject", "reason": "uninit_reg"}
        return None

    if op in ("ja", "exit"):
        return None

    return None


def refine_branch_types(op, insn, fall_regs, target_regs, fall_pkt, target_pkt):
    dst = insn.get("dst", 0)
    src = insn.get("src", 0)
    imm = insn.get("imm", 0)

    if op == "jeq_imm" and imm == 0:
        if fall_regs[dst] == RegType.PTR_TO_MAP_VALUE_OR_NULL:
            fall_regs[dst] = RegType.PTR_TO_MAP_VALUE
            target_regs[dst] = RegType.SCALAR

    elif op == "jne_imm" and imm == 0:
        if fall_regs[dst] == RegType.PTR_TO_MAP_VALUE_OR_NULL:
            fall_regs[dst] = RegType.SCALAR
            target_regs[dst] = RegType.PTR_TO_MAP_VALUE

    if op == "jgt_reg":
        if fall_regs[src] == RegType.PTR_TO_PACKET_END:
            for r in range(11):
                if fall_regs[r] == RegType.PTR_TO_PACKET:
                    fall_pkt[r] = True

    if op == "jge_reg":
        if fall_regs[src] == RegType.PTR_TO_PACKET_END:
            for r in range(11):
                if fall_regs[r] == RegType.PTR_TO_PACKET:
                    fall_pkt[r] = True


def verify_program(prog):
    instructions = prog["instructions"]
    prog_type = prog.get("prog_type", "xdp")
    n = len(instructions)

    if n == 0:
        return {"verdict": "reject", "reason": "no_exit"}

    succs = build_cfg(instructions)

    err = check_loops(instructions, succs)
    if err:
        return err

    err = check_reachability(instructions, succs)
    if err:
        return err

    err = check_exit_coverage(instructions, succs)
    if err:
        return err

    init_regs = [RegType.NOT_INIT] * 11
    init_regs[1] = RegType.PTR_TO_CTX
    init_regs[10] = RegType.PTR_TO_STACK

    dfs_stack = [(0, list(init_regs), {})]
    visited = {}

    while dfs_stack:
        idx, regs, pkt_bounds = dfs_stack.pop()

        if idx < 0 or idx >= n:
            continue

        state_key = (tuple(regs), tuple(sorted(pkt_bounds.items())))
        if idx not in visited:
            visited[idx] = set()
        if state_key in visited[idx]:
            continue
        visited[idx].add(state_key)

        insn = instructions[idx]
        op = insn["op"]

        if op == "exit":
            continue

        new_regs = list(regs)
        new_pkt = dict(pkt_bounds)
        err = check_instruction(insn, new_regs, new_pkt, prog_type, idx)
        if err:
            return err

        if op in ALL_CONDITIONAL_JUMPS:
            fall_idx = succs[idx][0]
            target_idx = succs[idx][1]

            fall_regs = list(new_regs)
            target_regs = list(new_regs)
            fall_pkt = dict(new_pkt)
            target_pkt = dict(new_pkt)

            refine_branch_types(op, insn, fall_regs, target_regs,
                                fall_pkt, target_pkt)

            dfs_stack.append((fall_idx, fall_regs, fall_pkt))
            dfs_stack.append((target_idx, target_regs, target_pkt))
        else:
            for s in succs.get(idx, []):
                dfs_stack.append((s, list(new_regs), dict(new_pkt)))

    return {"verdict": "accept"}


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <program.o>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    # Parse ELF and extract BPF program
    prog = parse_elf(filepath)

    # Verify safety properties
    result = verify_program(prog)

    # Get disassembly from llvm-objdump-18
    disasm = get_disasm(filepath)
    result["disasm"] = disasm

    print(json.dumps(result))


if __name__ == "__main__":
    main()
