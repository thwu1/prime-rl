#!/usr/bin/env python3
"""BPF ELF Object File Analyzer.

Parses compiled BPF ELF object files and produces a structured JSON report
containing program sections, instruction analysis, and map definitions.
"""

import json
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


# ── BPF instruction class constants ──────────────────────────────────────────
BPF_LD    = 0x00
BPF_LDX   = 0x01
BPF_ST    = 0x02
BPF_STX   = 0x03
BPF_ALU   = 0x04
BPF_JMP   = 0x05
BPF_JMP32 = 0x06
BPF_ALU64 = 0x07

# JMP sub-operations (upper nibble of opcode for JMP/JMP32 class)
BPF_JMP_CALL = 0x80
BPF_JMP_EXIT = 0x90

# lddw opcode: BPF_LD (0x00) | BPF_DW (0x18) | BPF_IMM (0x00)
OPCODE_LDDW = 0x18

# BPF_CALL opcode: BPF_JMP (0x05) | BPF_CALL (0x80)
OPCODE_CALL = 0x85

# BPF_EXIT opcode: BPF_JMP (0x05) | BPF_EXIT (0x90)
OPCODE_EXIT = 0x95


# ── Helper function ID → name mapping ────────────────────────────────────────
BPF_HELPER_NAMES = {
    1:  "bpf_map_lookup_elem",
    2:  "bpf_map_update_elem",
    3:  "bpf_map_delete_elem",
    4:  "bpf_probe_read",
    5:  "bpf_ktime_get_ns",
    6:  "bpf_trace_printk",
    7:  "bpf_get_prandom_u32",
    8:  "bpf_get_smp_processor_id",
    9:  "bpf_skb_store_bytes",
    10: "bpf_l3_csum_replace",
    11: "bpf_l4_csum_replace",
    12: "bpf_tail_call",
    13: "bpf_clone_redirect",
    14: "bpf_get_current_pid_tgid",
    15: "bpf_get_current_uid_gid",
    16: "bpf_get_current_comm",
    17: "bpf_get_cgroup_classid",
    18: "bpf_skb_vlan_push",
    19: "bpf_skb_vlan_pop",
    20: "bpf_skb_get_tunnel_key",
    21: "bpf_skb_set_tunnel_key",
    22: "bpf_perf_event_read",
    23: "bpf_redirect",
    24: "bpf_get_route_realm",
    25: "bpf_perf_event_output",
    26: "bpf_skb_load_bytes",
    27: "bpf_get_stackid",
    28: "bpf_csum_diff",
    29: "bpf_skb_get_tunnel_opt",
    30: "bpf_skb_set_tunnel_opt",
    31: "bpf_skb_change_proto",
    32: "bpf_skb_change_type",
    33: "bpf_skb_under_cgroup",
    34: "bpf_get_hash_recalc",
    35: "bpf_get_current_task",
    36: "bpf_probe_write_user",
    37: "bpf_current_task_under_cgroup",
    38: "bpf_skb_change_tail",
    39: "bpf_skb_pull_data",
    40: "bpf_csum_update",
    41: "bpf_set_hash_invalid",
    42: "bpf_get_numa_node_id",
    43: "bpf_skb_change_head",
    44: "bpf_xdp_adjust_head",
    45: "bpf_probe_read_str",
    46: "bpf_get_socket_cookie",
    47: "bpf_get_socket_uid",
    48: "bpf_set_hash",
    49: "bpf_setsockopt",
    50: "bpf_skb_adjust_room",
    51: "bpf_redirect_map",
    52: "bpf_sk_redirect_map",
    53: "bpf_sock_map_update",
    54: "bpf_xdp_adjust_meta",
    55: "bpf_perf_event_read_value",
    56: "bpf_perf_prog_read_value",
    57: "bpf_getsockopt",
    58: "bpf_override_return",
    59: "bpf_sock_ops_cb_flags_set",
    60: "bpf_msg_redirect_map",
    61: "bpf_msg_apply_bytes",
    62: "bpf_msg_cork_bytes",
    63: "bpf_msg_pull_data",
    64: "bpf_bind",
    65: "bpf_xdp_adjust_tail",
    66: "bpf_skb_get_xfrm_state",
    67: "bpf_get_stack",
    68: "bpf_skb_load_bytes_relative",
    69: "bpf_fib_lookup",
    70: "bpf_sock_hash_update",
    71: "bpf_msg_redirect_hash",
    72: "bpf_sk_redirect_hash",
    73: "bpf_lwt_push_encap",
    74: "bpf_lwt_seg6_store_bytes",
    75: "bpf_lwt_seg6_adjust_srh",
    76: "bpf_lwt_seg6_action",
    77: "bpf_rc_repeat",
    78: "bpf_rc_keydown",
    79: "bpf_skb_cgroup_id",
    80: "bpf_get_current_cgroup_id",
    81: "bpf_get_local_storage",
    82: "bpf_sk_select_reuseport",
    83: "bpf_skb_ancestor_cgroup_id",
    84: "bpf_sk_lookup_tcp",
    85: "bpf_sk_lookup_udp",
    86: "bpf_sk_release",
    87: "bpf_map_push_elem",
    88: "bpf_map_pop_elem",
    89: "bpf_map_peek_elem",
    90: "bpf_msg_push_data",
    91: "bpf_msg_pop_data",
    92: "bpf_rc_pointer_rel",
}


# ── BPF map type ID → name mapping ───────────────────────────────────────────
BPF_MAP_TYPE_NAMES = {
    0:  "BPF_MAP_TYPE_UNSPEC",
    1:  "BPF_MAP_TYPE_HASH",
    2:  "BPF_MAP_TYPE_ARRAY",
    3:  "BPF_MAP_TYPE_PROG_ARRAY",
    4:  "BPF_MAP_TYPE_PERF_EVENT_ARRAY",
    5:  "BPF_MAP_TYPE_PERCPU_HASH",
    6:  "BPF_MAP_TYPE_PERCPU_ARRAY",
    7:  "BPF_MAP_TYPE_STACK_TRACE",
    8:  "BPF_MAP_TYPE_CGROUP_ARRAY",
    9:  "BPF_MAP_TYPE_LRU_HASH",
    10: "BPF_MAP_TYPE_LRU_PERCPU_HASH",
    11: "BPF_MAP_TYPE_LPM_TRIE",
    12: "BPF_MAP_TYPE_ARRAY_OF_MAPS",
    13: "BPF_MAP_TYPE_HASH_OF_MAPS",
    14: "BPF_MAP_TYPE_DEVMAP",
    15: "BPF_MAP_TYPE_SOCKMAP",
    16: "BPF_MAP_TYPE_CPUMAP",
    17: "BPF_MAP_TYPE_XSKMAP",
    18: "BPF_MAP_TYPE_SOCKHASH",
    19: "BPF_MAP_TYPE_CGROUP_STORAGE",
    20: "BPF_MAP_TYPE_REUSEPORT_SOCKARRAY",
    21: "BPF_MAP_TYPE_PERCPU_CGROUP_STORAGE",
    22: "BPF_MAP_TYPE_QUEUE",
    23: "BPF_MAP_TYPE_STACK",
    24: "BPF_MAP_TYPE_SK_STORAGE",
    25: "BPF_MAP_TYPE_DEVMAP_HASH",
    26: "BPF_MAP_TYPE_STRUCT_OPS",
    27: "BPF_MAP_TYPE_RINGBUF",
    28: "BPF_MAP_TYPE_INODE_STORAGE",
    29: "BPF_MAP_TYPE_TASK_STORAGE",
    30: "BPF_MAP_TYPE_BLOOM_FILTER",
}


# ── ELF section flags ────────────────────────────────────────────────────────
SHF_EXECINSTR = 0x4


# ── Sections that are never BPF programs ──────────────────────────────────────
_NON_PROGRAM_SECTIONS = frozenset([
    "", ".BTF", ".BTF.ext", ".maps", "maps", "license",
    ".data", ".bss", ".rodata", ".comment", ".note",
    ".eh_frame", ".symtab", ".strtab", ".shstrtab",
])


def _detect_endian(elf):
    """Return struct format character for the ELF's byte order."""
    return "<" if elf.little_endian else ">"


def decode_instructions(data, endian):
    """Decode BPF instructions from raw section bytes.

    Each BPF instruction is 8 bytes:
        byte 0:   opcode
        byte 1:   dst_reg (low nibble) | src_reg (high nibble)
        bytes 2-3: offset (signed 16-bit)
        bytes 4-7: immediate (signed 32-bit)

    The lddw instruction (opcode 0x18) spans two 8-byte slots.  The second
    slot carries the upper 32 bits of the 64-bit immediate; its opcode byte
    is 0x00.  We count lddw as *one* logical instruction.
    """
    instructions = []
    i = 0
    while i < len(data):
        if i + 8 > len(data):
            break

        code = data[i]
        regs = data[i + 1]
        dst_reg = regs & 0x0F
        src_reg = (regs >> 4) & 0x0F
        off = struct.unpack_from(f"{endian}h", data, i + 2)[0]
        imm = struct.unpack_from(f"{endian}i", data, i + 4)[0]

        insn = {
            "code": code,
            "dst_reg": dst_reg,
            "src_reg": src_reg,
            "off": off,
            "imm": imm,
            "is_lddw": False,
        }

        if code == OPCODE_LDDW:
            insn["is_lddw"] = True
            # Skip the continuation slot (second 8 bytes)
            i += 16
        else:
            i += 8

        instructions.append(insn)

    return instructions


def analyze_program_section(instructions):
    """Derive analytics from a list of decoded BPF instructions."""
    helpers = set()
    registers = set()
    max_stack_depth = 0
    has_backward_jumps = False

    for idx, insn in enumerate(instructions):
        code = insn["code"]
        dst  = insn["dst_reg"]
        src  = insn["src_reg"]
        off  = insn["off"]
        imm  = insn["imm"]
        insn_class = code & 0x07

        # ── Register tracking ────────────────────────────────────────────
        if insn["is_lddw"]:
            # lddw: only dst_reg is meaningful (src_reg encodes reloc type)
            registers.add(dst)
        elif insn_class in (BPF_ALU, BPF_ALU64):
            registers.add(dst)
            if code & 0x08:  # BPF_X → source is a register
                registers.add(src)
        elif insn_class in (BPF_JMP, BPF_JMP32):
            op = code & 0xF0
            if op == BPF_JMP_CALL:
                # CALL: r0 receives return value (implicitly), but the
                # encoding has dst=0 src=0 which is not a register operand.
                pass
            elif op == BPF_JMP_EXIT:
                registers.add(0)  # EXIT reads r0
            elif op == 0x00:
                # JA (unconditional jump): no register operands
                pass
            else:
                # Conditional jumps: dst is compared
                registers.add(dst)
                if code & 0x08:
                    registers.add(src)
        elif insn_class == BPF_LDX:
            registers.add(dst)
            registers.add(src)
        elif insn_class == BPF_ST:
            registers.add(dst)
        elif insn_class == BPF_STX:
            registers.add(dst)
            registers.add(src)
        elif insn_class == BPF_LD and not insn["is_lddw"]:
            registers.add(dst)

        # ── Helper call detection ────────────────────────────────────────
        if code == OPCODE_CALL:
            # src_reg == 0 means kernel helper (vs. BPF-to-BPF call where src=1)
            if src == 0:
                helpers.add(imm)

        # ── Backward jump detection ──────────────────────────────────────
        if insn_class in (BPF_JMP, BPF_JMP32):
            op = code & 0xF0
            if op != BPF_JMP_CALL and op != BPF_JMP_EXIT:
                if off < 0:
                    has_backward_jumps = True

        # ── Stack depth from R10-relative memory ops ─────────────────────
        if insn_class in (BPF_ST, BPF_STX) and dst == 10:
            if off < 0:
                max_stack_depth = max(max_stack_depth, -off)
        if insn_class == BPF_LDX and src == 10:
            if off < 0:
                max_stack_depth = max(max_stack_depth, -off)

    helpers_sorted = sorted(helpers)
    helper_names = [
        BPF_HELPER_NAMES.get(h, f"helper#{h}") for h in helpers_sorted
    ]

    return {
        "num_instructions": len(instructions),
        "helpers": helpers_sorted,
        "helper_names": helper_names,
        "max_stack_depth": max_stack_depth,
        "registers_used": sorted(registers),
        "has_backward_jumps": has_backward_jumps,
    }


def is_program_section(section):
    """Return True if the ELF section contains BPF program bytecode."""
    if section["sh_type"] != "SHT_PROGBITS":
        return False
    if not (section["sh_flags"] & SHF_EXECINSTR):
        return False
    if section["sh_size"] == 0 or section["sh_size"] % 8 != 0:
        return False
    if section.name in _NON_PROGRAM_SECTIONS:
        return False
    if section.name.startswith(".rel"):
        return False
    return True


def extract_maps(elf, endian):
    """Extract legacy BPF map definitions from the 'maps' section.

    Legacy maps use ``struct bpf_map_def SEC("maps") = { ... };``.  The
    section named "maps" holds the raw struct data (5 × uint32 = 20 bytes
    each).  Symbol table entries locate individual maps within the section.
    """
    maps = []

    # Locate the "maps" section and its index
    maps_section = None
    maps_section_idx = None
    for idx, section in enumerate(elf.iter_sections()):
        if section.name == "maps":
            maps_section = section
            maps_section_idx = idx
            break

    if maps_section is None:
        return maps

    maps_data = maps_section.data()

    # Find the symbol table
    symtab = None
    for section in elf.iter_sections():
        if isinstance(section, SymbolTableSection):
            symtab = section
            break

    if symtab is None:
        return maps

    for sym in symtab.iter_symbols():
        # Match symbols that belong to the maps section
        if sym["st_shndx"] != maps_section_idx:
            continue
        if not sym.name:
            continue
        # Skip section-type symbols (STT_SECTION has info == 3)
        if sym["st_info"]["type"] == "STT_SECTION":
            continue

        offset = sym["st_value"]
        # Each bpf_map_def is 20 bytes: 5 × uint32
        if offset + 20 > len(maps_data):
            continue

        type_val, key_size, value_size, max_entries, _map_flags = struct.unpack_from(
            f"{endian}IIIII", maps_data, offset
        )
        maps.append({
            "name": sym.name,
            "type": type_val,
            "type_name": BPF_MAP_TYPE_NAMES.get(
                type_val, f"BPF_MAP_TYPE_UNKNOWN({type_val})"
            ),
            "key_size": key_size,
            "value_size": value_size,
            "max_entries": max_entries,
        })

    maps.sort(key=lambda m: m["name"])
    return maps


def analyze_elf(filepath):
    """Analyze a BPF ELF object file and return the report dict."""
    with open(filepath, "rb") as f:
        elf = ELFFile(f)
        endian = _detect_endian(elf)

        program_sections = []
        for section in elf.iter_sections():
            if not is_program_section(section):
                continue
            data = section.data()
            instructions = decode_instructions(data, endian)
            analysis = analyze_program_section(instructions)
            program_sections.append({
                "name": section.name,
                "num_instructions": analysis["num_instructions"],
                "helpers": analysis["helpers"],
                "helper_names": analysis["helper_names"],
                "max_stack_depth": analysis["max_stack_depth"],
                "registers_used": analysis["registers_used"],
                "has_backward_jumps": analysis["has_backward_jumps"],
            })

        maps = extract_maps(elf, endian)

    return {
        "filename": Path(filepath).name,
        "program_sections": program_sections,
        "maps": maps,
    }


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bpf_elf_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    result = analyze_elf(filepath)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
