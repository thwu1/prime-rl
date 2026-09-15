#!/usr/bin/env python3
"""
Generate eBPF bytecode test programs for the static analyzer task.
Each program is a sequence of 8-byte eBPF instructions written as raw binary.
"""

import struct
import json
import os


def insn(code, dst, src, off, imm):
    """Encode a single 8-byte eBPF instruction (little-endian)."""
    regs = ((src & 0xf) << 4) | (dst & 0xf)
    return struct.pack('<BBhi', code, regs, off, imm)


def write_program(path, instructions):
    with open(path, 'wb') as f:
        for i in instructions:
            f.write(i)


os.makedirs('/app/programs', exist_ok=True)
os.makedirs('/app/results', exist_ok=True)

# ============================================================
# Program 1: null_deref
# Missing NULL check after bpf_map_lookup_elem.
# The return value R0 is dereferenced at insn 6 without
# checking if R0 == 0 (NULL).
# ============================================================
null_deref = [
    insn(0x62, 10, 0, -4, 0),      # 0: *(u32*)(r10-4) = 0       store key on stack
    insn(0xbf, 2, 10, 0, 0),       # 1: r2 = r10
    insn(0x07, 2, 0, 0, -4),       # 2: r2 += -4                 r2 = &key
    insn(0x18, 1, 1, 0, 1),        # 3: r1 = map_fd 1 (lo)       LD_IMM64 pseudo map fd
    insn(0x00, 0, 0, 0, 0),        # 4: (continuation)
    insn(0x85, 0, 0, 0, 1),        # 5: call bpf_map_lookup_elem  r0 = result or NULL
    insn(0x79, 1, 0, 0, 0),        # 6: r1 = *(u64*)(r0+0)       BUG: r0 may be NULL
    insn(0xb7, 0, 0, 0, 2),        # 7: r0 = 2                   XDP_PASS
    insn(0x95, 0, 0, 0, 0),        # 8: exit
]
write_program('/app/programs/null_deref.bin', null_deref)

# ============================================================
# Program 2: packet_oob
# XDP program accesses packet data without bounds check.
# Loads from ctx->data (offset 0) and ctx->data_end (offset 4)
# but dereferences the data pointer without checking
# data + N <= data_end.
# ============================================================
packet_oob = [
    insn(0xbf, 6, 1, 0, 0),       # 0: r6 = r1                  save xdp_md ctx
    insn(0x61, 2, 6, 0, 0),       # 1: r2 = *(u32*)(r6+0)       r2 = ctx->data
    insn(0x61, 3, 6, 4, 0),       # 2: r3 = *(u32*)(r6+4)       r3 = ctx->data_end
    insn(0x71, 0, 2, 23, 0),      # 3: r0 = *(u8*)(r2+23)       BUG: no bounds check
    insn(0xb7, 0, 0, 0, 2),       # 4: r0 = 2                   XDP_PASS
    insn(0x95, 0, 0, 0, 0),       # 5: exit
]
write_program('/app/programs/packet_oob.bin', packet_oob)

# ============================================================
# Program 3: unreachable
# Contains dead code after an unconditional jump.
# Instructions 2 and 3 are never reached from entry.
# ============================================================
unreachable = [
    insn(0xb7, 0, 0, 0, 1),       # 0: r0 = 1                   XDP_DROP
    insn(0x05, 0, 0, 2, 0),       # 1: goto +2                  jump to insn 4
    insn(0xb7, 0, 0, 0, 2),       # 2: r0 = 2                   UNREACHABLE
    insn(0xb7, 0, 0, 0, 3),       # 3: r0 = 3                   UNREACHABLE
    insn(0x95, 0, 0, 0, 0),       # 4: exit
]
write_program('/app/programs/unreachable.bin', unreachable)

# ============================================================
# Program 4: stack_oob
# Accesses stack memory at R10-516, which is below the
# eBPF stack limit of -512 relative to the frame pointer.
# ============================================================
stack_oob = [
    insn(0x62, 10, 0, -516, 0),   # 0: *(u32*)(r10-516) = 0     BUG: below -512 limit
    insn(0xb7, 0, 0, 0, 0),       # 1: r0 = 0
    insn(0x95, 0, 0, 0, 0),       # 2: exit
]
write_program('/app/programs/stack_oob.bin', stack_oob)

# ============================================================
# Program 5: valid_xdp
# Correctly written XDP program with proper bounds check
# before accessing packet data. No verification issues.
# ============================================================
valid_xdp = [
    insn(0xbf, 6, 1, 0, 0),       # 0:  r6 = r1                 save ctx
    insn(0x61, 2, 6, 0, 0),       # 1:  r2 = *(u32*)(r6+0)      data
    insn(0x61, 3, 6, 4, 0),       # 2:  r3 = *(u32*)(r6+4)      data_end
    insn(0xbf, 4, 2, 0, 0),       # 3:  r4 = r2                 copy data ptr
    insn(0x07, 4, 0, 0, 34),      # 4:  r4 += 34                data + eth + ip hdr
    insn(0x2d, 4, 3, 3, 0),       # 5:  if r4 > r3 goto +3      bounds check -> insn 9
    insn(0x71, 1, 2, 23, 0),      # 6:  r1 = *(u8*)(r2+23)      safe: IP protocol
    insn(0xb7, 0, 0, 0, 2),       # 7:  r0 = 2                  XDP_PASS
    insn(0x95, 0, 0, 0, 0),       # 8:  exit
    insn(0xb7, 0, 0, 0, 1),       # 9:  r0 = 1                  XDP_DROP
    insn(0x95, 0, 0, 0, 0),       # 10: exit
]
write_program('/app/programs/valid_xdp.bin', valid_xdp)

# ============================================================
# Program 6: valid_map
# Correctly uses bpf_map_lookup_elem with proper NULL check
# before dereferencing the result. No verification issues.
# ============================================================
valid_map = [
    insn(0x62, 10, 0, -4, 0),     # 0:  *(u32*)(r10-4) = 0      key = 0
    insn(0xbf, 2, 10, 0, 0),      # 1:  r2 = r10
    insn(0x07, 2, 0, 0, -4),      # 2:  r2 += -4                r2 = &key
    insn(0x18, 1, 1, 0, 1),       # 3:  r1 = map_fd 1 (lo)      LD_IMM64
    insn(0x00, 0, 0, 0, 0),       # 4:  (continuation)
    insn(0x85, 0, 0, 0, 1),       # 5:  call bpf_map_lookup_elem
    insn(0x15, 0, 0, 3, 0),       # 6:  if r0 == 0 goto +3      NULL check -> insn 10
    insn(0x79, 1, 0, 0, 0),       # 7:  r1 = *(u64*)(r0+0)      safe: r0 is non-NULL
    insn(0xb7, 0, 0, 0, 2),       # 8:  r0 = 2                  XDP_PASS
    insn(0x95, 0, 0, 0, 0),       # 9:  exit
    insn(0xb7, 0, 0, 0, 1),       # 10: r0 = 1                  XDP_DROP (null path)
    insn(0x95, 0, 0, 0, 0),       # 11: exit
]
write_program('/app/programs/valid_map.bin', valid_map)

# ============================================================
# Write metadata describing each program
# ============================================================
metadata = {
    "programs": {
        "null_deref": {
            "file": "null_deref.bin",
            "type": "xdp",
            "maps": [
                {"fd": 1, "type": "BPF_MAP_TYPE_HASH", "key_size": 4, "value_size": 8, "max_entries": 1024}
            ]
        },
        "packet_oob": {
            "file": "packet_oob.bin",
            "type": "xdp",
            "maps": []
        },
        "unreachable": {
            "file": "unreachable.bin",
            "type": "xdp",
            "maps": []
        },
        "stack_oob": {
            "file": "stack_oob.bin",
            "type": "xdp",
            "maps": []
        },
        "valid_xdp": {
            "file": "valid_xdp.bin",
            "type": "xdp",
            "maps": []
        },
        "valid_map": {
            "file": "valid_map.bin",
            "type": "xdp",
            "maps": [
                {"fd": 1, "type": "BPF_MAP_TYPE_HASH", "key_size": 4, "value_size": 8, "max_entries": 1024}
            ]
        }
    }
}

with open('/app/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print("Generated 6 eBPF bytecode programs and metadata.json")
