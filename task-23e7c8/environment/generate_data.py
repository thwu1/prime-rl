#!/usr/bin/env python3
"""Generate eBPF program data for dead code analysis task.

Creates BPF ELF relocatable object files for each program.
Creates an SQLite database with map definitions, program metadata,
rodata layout, and feature configurations.
"""

import sqlite3
import struct
import os


# ========== BPF Instruction Encoding ==========

def encode_insn(opcode, dst, src, off, imm):
    return struct.pack('<BBhi', opcode, (src << 4) | dst, off, imm)

def encode_lddw(dst, src, imm_lower):
    return (encode_insn(0x18, dst, src, 0, imm_lower)
            + encode_insn(0x00, 0, 0, 0, 0))

def mov64_reg(dst, src):    return encode_insn(0xbf, dst, src, 0, 0)
def mov64_imm(dst, imm):    return encode_insn(0xb7, dst, 0, 0, imm)
def ldxw(dst, src, off):    return encode_insn(0x61, dst, src, off, 0)
def jeq_imm(dst, imm, off): return encode_insn(0x15, dst, 0, off, imm)
def jne_imm(dst, imm, off): return encode_insn(0x55, dst, 0, off, imm)
def jlt_imm(dst, imm, off): return encode_insn(0xa5, dst, 0, off, imm)
def jle_imm(dst, imm, off): return encode_insn(0xb5, dst, 0, off, imm)
def call_helper(helper_id): return encode_insn(0x85, 0, 0, 0, helper_id)
def bpf_exit():             return encode_insn(0x95, 0, 0, 0, 0)


# ========== ELF Object File Builder ==========

def build_elf_object(bytecode, relocations):
    """Build a BPF ELF relocatable object from bytecodes and relocations.

    Args:
        bytecode: bytes of BPF instructions
        relocations: list of {'insn_idx': int, 'map_name': str}
    Returns:
        Complete ELF file as bytes
    """
    # Unique map names in order of first appearance
    map_order = []
    seen = set()
    for r in relocations:
        if r['map_name'] not in seen:
            map_order.append(r['map_name'])
            seen.add(r['map_name'])

    # String table (.strtab) for symbol names
    strtab = bytearray(b'\x00')
    str_off = {}
    for name in map_order:
        str_off[name] = len(strtab)
        strtab += name.encode() + b'\x00'
    strtab = bytes(strtab)

    # Symbol table (.symtab)
    # Entry 0: NULL symbol (required by ELF spec)
    syms = struct.pack('<IBBHQQ', 0, 0, 0, 0, 0, 0)
    sym_idx = {}
    for i, name in enumerate(map_order):
        sym_idx[name] = i + 1
        st_info = (1 << 4) | 0  # STB_GLOBAL | STT_NOTYPE
        syms += struct.pack('<IBBHQQ', str_off[name], st_info, 0, 0, 0, 0)

    # Relocation table (.rela.text)
    rela = b''
    for r in relocations:
        sidx = sym_idx[r['map_name']]
        r_offset = r['insn_idx'] * 8
        r_info = (sidx << 32) | 1  # R_BPF_64_64
        rela += struct.pack('<QQq', r_offset, r_info, 0)

    # Section name string table (.shstrtab) — fixed layout
    shstrtab = b'\x00.text\x00.rela.text\x00.symtab\x00.strtab\x00.shstrtab\x00'
    SHN = {'.text': 1, '.rela.text': 7, '.symtab': 18,
           '.strtab': 26, '.shstrtab': 34}

    # Compute file layout (all offsets from start of file)
    off = 64  # after ELF header (64 bytes)
    t_off = off;  t_sz = len(bytecode);   off += t_sz
    r_off = off;  r_sz = len(rela);       off += r_sz
    s_off = off;  s_sz = len(syms);       off += s_sz
    st_off = off; st_sz = len(strtab);    off += st_sz
    sh_off = off; sh_sz = len(shstrtab);  off += sh_sz
    pad = (8 - off % 8) % 8;             off += pad
    shdr_off = off

    # ELF header (64 bytes)
    ident = b'\x7fELF\x02\x01\x01' + b'\x00' * 9
    ehdr = struct.pack('<16sHHIQQQIHHHHHH',
        ident,
        1,          # e_type = ET_REL
        247,        # e_machine = EM_BPF
        1,          # e_version = EV_CURRENT
        0,          # e_entry
        0,          # e_phoff
        shdr_off,   # e_shoff
        0,          # e_flags
        64,         # e_ehsize
        0,          # e_phentsize
        0,          # e_phnum
        64,         # e_shentsize
        6,          # e_shnum
        5)          # e_shstrndx

    # Section headers (6 x 64 bytes)
    P = '<IIQQQQIIQQ'
    shdrs  = struct.pack(P, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)  # NULL
    shdrs += struct.pack(P, SHN['.text'], 1, 6, 0,
                         t_off, t_sz, 0, 0, 8, 0)            # .text (PROGBITS)
    shdrs += struct.pack(P, SHN['.rela.text'], 4, 0, 0,
                         r_off, r_sz, 3, 1, 8, 24)           # .rela.text (RELA)
    shdrs += struct.pack(P, SHN['.symtab'], 2, 0, 0,
                         s_off, s_sz, 4, 1, 8, 24)           # .symtab (SYMTAB)
    shdrs += struct.pack(P, SHN['.strtab'], 3, 0, 0,
                         st_off, st_sz, 0, 0, 1, 0)          # .strtab (STRTAB)
    shdrs += struct.pack(P, SHN['.shstrtab'], 3, 0, 0,
                         sh_off, sh_sz, 0, 0, 1, 0)          # .shstrtab (STRTAB)

    return ehdr + bytecode + rela + syms + strtab + shstrtab + b'\x00' * pad + shdrs


# ========== Map Definitions ==========

MAPS = [
    {"id": 0,  "name": ".rodata",          "type": "BPF_MAP_TYPE_ARRAY",
     "key_size": 4, "value_size": 40, "max_entries": 1},
    {"id": 1,  "name": "conn_track_map",    "type": "BPF_MAP_TYPE_HASH",
     "key_size": 16, "value_size": 32, "max_entries": 65536},
    {"id": 2,  "name": "nat_map",           "type": "BPF_MAP_TYPE_HASH",
     "key_size": 8, "value_size": 24, "max_entries": 4096},
    {"id": 3,  "name": "metrics_map",       "type": "BPF_MAP_TYPE_PERCPU_ARRAY",
     "key_size": 4, "value_size": 64, "max_entries": 256},
    {"id": 4,  "name": "policy_map",        "type": "BPF_MAP_TYPE_HASH",
     "key_size": 12, "value_size": 8, "max_entries": 16384},
    {"id": 5,  "name": "tunnel_map",        "type": "BPF_MAP_TYPE_HASH",
     "key_size": 4, "value_size": 20, "max_entries": 256},
    {"id": 6,  "name": "lb_backends_map",   "type": "BPF_MAP_TYPE_HASH",
     "key_size": 4, "value_size": 16, "max_entries": 1024},
    {"id": 7,  "name": "lb_services_map",   "type": "BPF_MAP_TYPE_HASH",
     "key_size": 8, "value_size": 12, "max_entries": 4096},
    {"id": 8,  "name": "tail_call_map",     "type": "BPF_MAP_TYPE_PROG_ARRAY",
     "key_size": 4, "value_size": 4, "max_entries": 8},
    {"id": 9,  "name": "rate_limit_map",    "type": "BPF_MAP_TYPE_HASH",
     "key_size": 8, "value_size": 16, "max_entries": 8192},
    {"id": 10, "name": "log_events_map",    "type": "BPF_MAP_TYPE_PERF_EVENT_ARRAY",
     "key_size": 4, "value_size": 4, "max_entries": 0},
    {"id": 11, "name": "acl_map",           "type": "BPF_MAP_TYPE_HASH",
     "key_size": 16, "value_size": 8, "max_entries": 32768},
    {"id": 12, "name": "encap_params_map",  "type": "BPF_MAP_TYPE_HASH",
     "key_size": 4, "value_size": 24, "max_entries": 256},
    {"id": 13, "name": "monitor_ring_buf",  "type": "BPF_MAP_TYPE_RINGBUF",
     "key_size": 0, "value_size": 0, "max_entries": 262144},
    {"id": 14, "name": "session_map",       "type": "BPF_MAP_TYPE_LRU_HASH",
     "key_size": 16, "value_size": 32, "max_entries": 131072},
]


# ========== Rodata Layout ==========

RODATA_FIELDS = [
    {"name": "enable_lb",         "offset": 0,  "size": 4, "type": "u32"},
    {"name": "enable_nat",        "offset": 4,  "size": 4, "type": "u32"},
    {"name": "enable_tunnel",     "offset": 8,  "size": 4, "type": "u32"},
    {"name": "enable_policy",     "offset": 12, "size": 4, "type": "u32"},
    {"name": "enable_conntrack",  "offset": 16, "size": 4, "type": "u32"},
    {"name": "rate_limit_mode",   "offset": 20, "size": 4, "type": "u32"},
    {"name": "enable_logging",    "offset": 24, "size": 4, "type": "u32"},
    {"name": "tunnel_mode",       "offset": 28, "size": 4, "type": "u32"},
    {"name": "monitor_level",     "offset": 32, "size": 4, "type": "u32"},
    {"name": "session_tracking",  "offset": 36, "size": 4, "type": "u32"},
]


# ========== Program Builders ==========

def build_xdp_main():
    """Entry program: dispatches to sub-programs via tail calls based
    on feature flags in .rodata."""
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r7, &.rodata
    relocations.append({"insn_idx": 1, "map_name": ".rodata"})
    bytecode += encode_lddw(7, 2, 0)

    features = [
        (0,  0),   # enable_lb -> tail_call index 0
        (4,  1),   # enable_nat -> tail_call index 1
        (8,  2),   # enable_tunnel -> tail_call index 2
        (12, 3),   # enable_policy -> tail_call index 3
        (32, 4),   # monitor_level -> tail_call index 4
    ]

    for rodata_off, tc_idx in features:
        base = len(bytecode) // 8
        bytecode += ldxw(8, 7, rodata_off)
        bytecode += jeq_imm(8, 0, 5)
        bytecode += mov64_reg(1, 6)
        relocations.append({"insn_idx": base + 3, "map_name": "tail_call_map"})
        bytecode += encode_lddw(2, 1, 8)
        bytecode += mov64_imm(3, tc_idx)
        bytecode += call_helper(12)

    # Default: XDP_PASS
    bytecode += mov64_imm(0, 2)
    bytecode += bpf_exit()

    return "xdp_main", bytecode, relocations, True, None


def build_xdp_lb():
    """Load balancer (tail_call_index=0).

    Uses: lb_services_map, lb_backends_map (always)
    Conditional: conn_track_map (enable_conntrack != 0)
    Conditional: rate_limit_map (rate_limit_mode >= 1, via JLT)
    Conditional: tail_call to xdp_acl (rate_limit_mode == 2, via JNE)
    Conditional: session_map (session_tracking != 0)
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r7, .rodata
    relocations.append({"insn_idx": 1, "map_name": ".rodata"})
    bytecode += encode_lddw(7, 2, 0)
    # 3-4: lddw r1, lb_services_map
    relocations.append({"insn_idx": 3, "map_name": "lb_services_map"})
    bytecode += encode_lddw(1, 1, 7)
    # 5: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 6: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 7: jeq r0, 0, +27 -> insn 35 (exit)
    bytecode += jeq_imm(0, 0, 27)
    # 8: mov r9, r0
    bytecode += mov64_reg(9, 0)
    # 9-10: lddw r1, lb_backends_map
    relocations.append({"insn_idx": 9, "map_name": "lb_backends_map"})
    bytecode += encode_lddw(1, 1, 6)
    # 11: mov r2, r9
    bytecode += mov64_reg(2, 9)
    # 12: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 13: jeq r0, 0, +21 -> insn 35 (exit)
    bytecode += jeq_imm(0, 0, 21)

    # --- conntrack check ---
    # 14: ldxw r8, [r7+16]  (enable_conntrack)
    bytecode += ldxw(8, 7, 16)
    # 15: jeq r8, 0, +3 -> insn 19
    bytecode += jeq_imm(8, 0, 3)
    # 16-17: lddw r1, conn_track_map
    relocations.append({"insn_idx": 16, "map_name": "conn_track_map"})
    bytecode += encode_lddw(1, 1, 1)
    # 18: call bpf_map_lookup_elem
    bytecode += call_helper(1)

    # --- rate limiting check (JLT + JNE) ---
    # 19: ldxw r8, [r7+20]  (rate_limit_mode)
    bytecode += ldxw(8, 7, 20)
    # 20: jlt r8, 1, +9 -> insn 30 (skip all rate limiting if < 1)
    bytecode += jlt_imm(8, 1, 9)
    # 21-22: lddw r1, rate_limit_map
    relocations.append({"insn_idx": 21, "map_name": "rate_limit_map"})
    bytecode += encode_lddw(1, 1, 9)
    # 23: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 24: jne r8, 2, +5 -> insn 30 (skip ACL tail call if != 2)
    bytecode += jne_imm(8, 2, 5)
    # 25: mov r1, r6
    bytecode += mov64_reg(1, 6)
    # 26-27: lddw r2, tail_call_map
    relocations.append({"insn_idx": 26, "map_name": "tail_call_map"})
    bytecode += encode_lddw(2, 1, 8)
    # 28: mov r3, 5  (xdp_acl)
    bytecode += mov64_imm(3, 5)
    # 29: call bpf_tail_call
    bytecode += call_helper(12)

    # --- session tracking check ---
    # 30: ldxw r8, [r7+36]  (session_tracking)
    bytecode += ldxw(8, 7, 36)
    # 31: jeq r8, 0, +3 -> insn 35
    bytecode += jeq_imm(8, 0, 3)
    # 32-33: lddw r1, session_map
    relocations.append({"insn_idx": 32, "map_name": "session_map"})
    bytecode += encode_lddw(1, 1, 14)
    # 34: call bpf_map_lookup_elem
    bytecode += call_helper(1)

    # 35: mov r0, 3 (XDP_TX)
    bytecode += mov64_imm(0, 3)
    # 36: exit
    bytecode += bpf_exit()

    return "xdp_lb", bytecode, relocations, False, 0


def build_xdp_nat():
    """NAT program (tail_call_index=1).

    Always uses: nat_map, conn_track_map (no feature gates).
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r1, nat_map
    relocations.append({"insn_idx": 1, "map_name": "nat_map"})
    bytecode += encode_lddw(1, 1, 2)
    # 3: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 4: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 5: jeq r0, 0, +5 -> insn 11 (exit)
    bytecode += jeq_imm(0, 0, 5)
    # 6: mov r9, r0
    bytecode += mov64_reg(9, 0)
    # 7-8: lddw r1, conn_track_map
    relocations.append({"insn_idx": 7, "map_name": "conn_track_map"})
    bytecode += encode_lddw(1, 1, 1)
    # 9: mov r2, r9
    bytecode += mov64_reg(2, 9)
    # 10: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 11: mov r0, 3
    bytecode += mov64_imm(0, 3)
    # 12: exit
    bytecode += bpf_exit()

    return "xdp_nat", bytecode, relocations, False, 1


def build_xdp_tunnel():
    """Tunnel program (tail_call_index=2).

    Always uses: tunnel_map
    Conditional: tail_call to xdp_encap (tunnel_mode == 2, via JNE)
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r7, .rodata
    relocations.append({"insn_idx": 1, "map_name": ".rodata"})
    bytecode += encode_lddw(7, 2, 0)
    # 3-4: lddw r1, tunnel_map
    relocations.append({"insn_idx": 3, "map_name": "tunnel_map"})
    bytecode += encode_lddw(1, 1, 5)
    # 5: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 6: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 7: ldxw r8, [r7+28]  (tunnel_mode)
    bytecode += ldxw(8, 7, 28)
    # 8: jne r8, 2, +5 -> insn 14 (skip encap if != 2)
    bytecode += jne_imm(8, 2, 5)
    # 9: mov r1, r6
    bytecode += mov64_reg(1, 6)
    # 10-11: lddw r2, tail_call_map
    relocations.append({"insn_idx": 10, "map_name": "tail_call_map"})
    bytecode += encode_lddw(2, 1, 8)
    # 12: mov r3, 6  (xdp_encap)
    bytecode += mov64_imm(3, 6)
    # 13: call bpf_tail_call
    bytecode += call_helper(12)
    # 14: mov r0, 3
    bytecode += mov64_imm(0, 3)
    # 15: exit
    bytecode += bpf_exit()

    return "xdp_tunnel", bytecode, relocations, False, 2


def build_xdp_policy():
    """Policy enforcement program (tail_call_index=3).

    Always uses: policy_map, metrics_map
    Conditional: log_events_map (enable_logging != 0)
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r7, .rodata
    relocations.append({"insn_idx": 1, "map_name": ".rodata"})
    bytecode += encode_lddw(7, 2, 0)
    # 3-4: lddw r1, policy_map
    relocations.append({"insn_idx": 3, "map_name": "policy_map"})
    bytecode += encode_lddw(1, 1, 4)
    # 5: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 6: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 7: jeq r0, 0, +9 -> insn 17 (exit)
    bytecode += jeq_imm(0, 0, 9)
    # 8-9: lddw r1, metrics_map
    relocations.append({"insn_idx": 8, "map_name": "metrics_map"})
    bytecode += encode_lddw(1, 1, 3)
    # 10: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 11: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 12: ldxw r8, [r7+24]  (enable_logging)
    bytecode += ldxw(8, 7, 24)
    # 13: jeq r8, 0, +3 -> insn 17 (skip logging)
    bytecode += jeq_imm(8, 0, 3)
    # 14-15: lddw r1, log_events_map
    relocations.append({"insn_idx": 14, "map_name": "log_events_map"})
    bytecode += encode_lddw(1, 1, 10)
    # 16: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 17: mov r0, 2
    bytecode += mov64_imm(0, 2)
    # 18: exit
    bytecode += bpf_exit()

    return "xdp_policy", bytecode, relocations, False, 3


def build_xdp_monitor():
    """Monitoring program (tail_call_index=4).

    Always uses: monitor_ring_buf, metrics_map
    Conditional: log_events_map (monitor_level > 2, via JLE)
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r7, .rodata
    relocations.append({"insn_idx": 1, "map_name": ".rodata"})
    bytecode += encode_lddw(7, 2, 0)
    # 3-4: lddw r1, monitor_ring_buf
    relocations.append({"insn_idx": 3, "map_name": "monitor_ring_buf"})
    bytecode += encode_lddw(1, 1, 13)
    # 5: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 6: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 7-8: lddw r1, metrics_map
    relocations.append({"insn_idx": 7, "map_name": "metrics_map"})
    bytecode += encode_lddw(1, 1, 3)
    # 9: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 10: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 11: ldxw r8, [r7+32]  (monitor_level)
    bytecode += ldxw(8, 7, 32)
    # 12: jle r8, 2, +3 -> insn 16 (skip detailed logging if <= 2)
    bytecode += jle_imm(8, 2, 3)
    # 13-14: lddw r1, log_events_map
    relocations.append({"insn_idx": 13, "map_name": "log_events_map"})
    bytecode += encode_lddw(1, 1, 10)
    # 15: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 16: mov r0, 2
    bytecode += mov64_imm(0, 2)
    # 17: exit
    bytecode += bpf_exit()

    return "xdp_monitor", bytecode, relocations, False, 4


def build_xdp_acl():
    """ACL program (tail_call_index=5).

    Always uses: acl_map, rate_limit_map. No feature gates.
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r1, acl_map
    relocations.append({"insn_idx": 1, "map_name": "acl_map"})
    bytecode += encode_lddw(1, 1, 11)
    # 3: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 4: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 5-6: lddw r1, rate_limit_map
    relocations.append({"insn_idx": 5, "map_name": "rate_limit_map"})
    bytecode += encode_lddw(1, 1, 9)
    # 7: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 8: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 9: mov r0, 1 (XDP_DROP)
    bytecode += mov64_imm(0, 1)
    # 10: exit
    bytecode += bpf_exit()

    return "xdp_acl", bytecode, relocations, False, 5


def build_xdp_encap():
    """Encapsulation program (tail_call_index=6).

    Always uses: encap_params_map, tunnel_map. No feature gates.
    """
    bytecode = b''
    relocations = []

    # 0: mov r6, r1
    bytecode += mov64_reg(6, 1)
    # 1-2: lddw r1, encap_params_map
    relocations.append({"insn_idx": 1, "map_name": "encap_params_map"})
    bytecode += encode_lddw(1, 1, 12)
    # 3: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 4: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 5-6: lddw r1, tunnel_map
    relocations.append({"insn_idx": 5, "map_name": "tunnel_map"})
    bytecode += encode_lddw(1, 1, 5)
    # 7: mov r2, r6
    bytecode += mov64_reg(2, 6)
    # 8: call bpf_map_lookup_elem
    bytecode += call_helper(1)
    # 9: mov r0, 3 (XDP_TX)
    bytecode += mov64_imm(0, 3)
    # 10: exit
    bytecode += bpf_exit()

    return "xdp_encap", bytecode, relocations, False, 6


# ========== Configuration Definitions ==========

CONFIGS = [
    {
        "name": "config_1",
        "description": "LB with advanced rate limiting, policy with logging",
        "values": {
            "enable_lb": 1, "enable_nat": 0, "enable_tunnel": 0,
            "enable_policy": 1, "enable_conntrack": 1,
            "rate_limit_mode": 2, "enable_logging": 1,
            "tunnel_mode": 0, "monitor_level": 0, "session_tracking": 0,
        },
    },
    {
        "name": "config_2",
        "description": "NAT with GRE tunneling",
        "values": {
            "enable_lb": 0, "enable_nat": 1, "enable_tunnel": 1,
            "enable_policy": 0, "enable_conntrack": 0,
            "rate_limit_mode": 0, "enable_logging": 0,
            "tunnel_mode": 2, "monitor_level": 0, "session_tracking": 0,
        },
    },
    {
        "name": "config_3",
        "description": "Full stack, high monitoring, basic rate limiting",
        "values": {
            "enable_lb": 1, "enable_nat": 1, "enable_tunnel": 1,
            "enable_policy": 1, "enable_conntrack": 1,
            "rate_limit_mode": 1, "enable_logging": 0,
            "tunnel_mode": 1, "monitor_level": 3, "session_tracking": 1,
        },
    },
    {
        "name": "config_4",
        "description": "Minimal LB with sessions, IPIP tunnel, low monitoring",
        "values": {
            "enable_lb": 1, "enable_nat": 0, "enable_tunnel": 1,
            "enable_policy": 0, "enable_conntrack": 0,
            "rate_limit_mode": 0, "enable_logging": 0,
            "tunnel_mode": 1, "monitor_level": 1, "session_tracking": 1,
        },
    },
    {
        "name": "config_5",
        "description": "All features disabled",
        "values": {
            "enable_lb": 0, "enable_nat": 0, "enable_tunnel": 0,
            "enable_policy": 0, "enable_conntrack": 0,
            "rate_limit_mode": 0, "enable_logging": 0,
            "tunnel_mode": 0, "monitor_level": 0, "session_tracking": 0,
        },
    },
]


# ========== Main ==========

def main():
    programs = [
        build_xdp_main(),
        build_xdp_lb(),
        build_xdp_nat(),
        build_xdp_tunnel(),
        build_xdp_policy(),
        build_xdp_monitor(),
        build_xdp_acl(),
        build_xdp_encap(),
    ]

    os.makedirs('/app/programs', exist_ok=True)
    os.makedirs('/app/results', exist_ok=True)

    db_path = '/app/ebpf_programs.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Create tables
    c.execute('''CREATE TABLE maps (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        type TEXT NOT NULL,
        key_size INTEGER NOT NULL,
        value_size INTEGER NOT NULL,
        max_entries INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE programs (
        name TEXT PRIMARY KEY,
        elf_file TEXT NOT NULL,
        is_entry INTEGER NOT NULL DEFAULT 0,
        tail_call_index INTEGER
    )''')

    c.execute('''CREATE TABLE rodata_layout (
        field_name TEXT PRIMARY KEY,
        byte_offset INTEGER NOT NULL,
        size INTEGER NOT NULL,
        field_type TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE configs (
        name TEXT PRIMARY KEY,
        description TEXT
    )''')

    c.execute('''CREATE TABLE config_values (
        config_name TEXT NOT NULL,
        field_name TEXT NOT NULL,
        value INTEGER NOT NULL,
        PRIMARY KEY (config_name, field_name),
        FOREIGN KEY (config_name) REFERENCES configs(name),
        FOREIGN KEY (field_name) REFERENCES rodata_layout(field_name)
    )''')

    c.execute('''CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    # Insert maps
    for m in MAPS:
        c.execute('INSERT INTO maps VALUES (?,?,?,?,?,?)',
                  (m['id'], m['name'], m['type'],
                   m['key_size'], m['value_size'], m['max_entries']))

    # Build ELF files and insert program metadata
    for name, bytecode, relocs, is_entry, tc_idx in programs:
        elf_path = f'/app/programs/{name}.o'
        elf_data = build_elf_object(bytecode, relocs)
        with open(elf_path, 'wb') as f:
            f.write(elf_data)

        c.execute('INSERT INTO programs VALUES (?,?,?,?)',
                  (name, elf_path, 1 if is_entry else 0, tc_idx))

    # Insert rodata layout
    for field in RODATA_FIELDS:
        c.execute('INSERT INTO rodata_layout VALUES (?,?,?,?)',
                  (field['name'], field['offset'], field['size'], field['type']))

    # Insert configs
    for config in CONFIGS:
        c.execute('INSERT INTO configs VALUES (?,?)',
                  (config['name'], config['description']))
        for field_name, value in config['values'].items():
            c.execute('INSERT INTO config_values VALUES (?,?,?)',
                      (config['name'], field_name, value))

    # Insert metadata
    c.execute("INSERT INTO metadata VALUES ('rodata_map_name', '.rodata')")
    c.execute("INSERT INTO metadata VALUES ('tail_call_map_name', 'tail_call_map')")
    c.execute("INSERT INTO metadata VALUES ('rodata_total_size', '40')")

    conn.commit()
    conn.close()

    print("Data generation complete.")
    print(f"  Database: {db_path}")
    print(f"  ELF files: /app/programs/ ({len(programs)} files)")
    print(f"  Maps: {len(MAPS)}")
    print(f"  Programs: {len(programs)}")
    print(f"  Configs: {len(CONFIGS)}")


if __name__ == '__main__':
    main()
