#!/usr/bin/env python3
"""Generate BPF ELF object files for the verifier task."""
import struct
import os
import base64

# ELF constants
SHT_NULL = 0
SHT_PROGBITS = 1
SHT_STRTAB = 3
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4


def make_bpf_elf(prog_type_id, insns_data, maps_data=b""):
    """Create a BPF ELF relocatable object file.

    Args:
        prog_type_id: 1=XDP, 2=kprobe, 3=tracepoint
        insns_data: raw BPF instructions (8 bytes each)
        maps_data: raw map descriptors (16 bytes each), or empty
    Returns:
        bytes: complete ELF file content
    """
    has_maps = len(maps_data) > 0

    # Build .shstrtab content
    shstrtab = b"\x00"
    name_text = len(shstrtab)
    shstrtab += b".text\x00"
    if has_maps:
        name_maps = len(shstrtab)
        shstrtab += b".maps\x00"
    name_meta = len(shstrtab)
    shstrtab += b".bpf_meta\x00"
    name_shstrtab = len(shstrtab)
    shstrtab += b".shstrtab\x00"

    meta_data = struct.pack("B", prog_type_id)

    # Compute data offsets (all sections placed sequentially after 64-byte ELF header)
    off = 64  # ELF header size

    text_off = off
    off += len(insns_data)

    if has_maps:
        maps_off = off
        off += len(maps_data)

    meta_off = off
    off += len(meta_data)

    strtab_off = off
    off += len(shstrtab)

    # Align section header table to 8 bytes
    shdr_off = (off + 7) & ~7

    # Section count: NULL + .text + [.maps] + .bpf_meta + .shstrtab
    num_sh = 4 + (1 if has_maps else 0)
    shstrndx = num_sh - 1

    # --- Build ELF header (64 bytes) ---
    e_ident = bytes([
        0x7f, 0x45, 0x4c, 0x46,  # magic
        2,    # ELFCLASS64
        1,    # ELFDATA2LSB
        1,    # EV_CURRENT
        0,    # ELFOSABI_NONE
        0, 0, 0, 0, 0, 0, 0, 0  # padding
    ])
    ehdr = e_ident + struct.pack("<HHIQQQIHHHHHH",
        1,          # e_type = ET_REL
        247,        # e_machine = EM_BPF
        1,          # e_version
        0,          # e_entry
        0,          # e_phoff
        shdr_off,   # e_shoff
        0,          # e_flags
        64,         # e_ehsize
        0,          # e_phentsize
        0,          # e_phnum
        64,         # e_shentsize
        num_sh,     # e_shnum
        shstrndx    # e_shstrndx
    )

    # --- Assemble file body ---
    blob = bytearray(ehdr)
    blob += insns_data
    if has_maps:
        blob += maps_data
    blob += meta_data
    blob += shstrtab
    # Pad to section header table offset
    blob += b"\x00" * (shdr_off - len(blob))

    # --- Section header entries (64 bytes each) ---
    def shdr(name, typ, flags, offset, size, align):
        return struct.pack("<IIQQQQIIQQ",
            name, typ, flags, 0, offset, size, 0, 0, align, 0)

    # [0] NULL
    blob += shdr(0, SHT_NULL, 0, 0, 0, 0)
    # [1] .text
    blob += shdr(name_text, SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR,
                 text_off, len(insns_data), 8)
    if has_maps:
        blob += shdr(name_maps, SHT_PROGBITS, SHF_ALLOC,
                     maps_off, len(maps_data), 4)
    # .bpf_meta
    blob += shdr(name_meta, SHT_PROGBITS, 0, meta_off, len(meta_data), 1)
    # .shstrtab
    blob += shdr(name_shstrtab, SHT_STRTAB, 0, strtab_off, len(shstrtab), 1)

    return bytes(blob)


# ── Programs encoded in legacy custom binary format ──
# Header: magic(4) version(1) prog_type(1) num_insns(2) num_maps(1) reserved(7)
# Maps: 16 bytes each (map_id, map_type, key_size, value_size as u32 LE)
# Instructions: 8 bytes each (opcode, regs, offset_s16, imm_s32)

PROGRAMS_B64 = {
    "simple_pass":   "f0JQRgEBAgAAAAAAAAAAALcAAAACAAAAlQAAAAAAAAA=",
    "null_deref":    "f0JQRgEBCAABAAAAAAAAAAAAAAABAAAABAAAAAgAAABiCvz/AAAAAL+iAAAAAAAABwIAAPz///+3AQAAAAAAAIUAAAABAAAAYQEAAAAAAAC3AAAAAgAAAJUAAAAAAAAA",
    "null_check_ok": "f0JQRgEBCwABAAAAAAAAAAAAAAABAAAABAAAAAgAAABiCvz/AAAAAL+iAAAAAAAABwIAAPz///+3AQAAAAAAAIUAAAABAAAAFQADAAAAAABhAQAAAAAAALcAAAACAAAAlQAAAAAAAAC3AAAAAQAAAJUAAAAAAAAA",
    "uninit_reg":    "f0JQRgEBAgAAAAAAAAAAAL9wAAAAAAAAlQAAAAAAAAA=",
    "loop_detected": "f0JQRgEBBgAAAAAAAAAAALcGAAAKAAAAtwAAAAAAAAAHAAAAAQAAAK1g/v8AAAAAtwAAAAIAAACVAAAAAAAAAA==",
    "unreachable":   "f0JQRgEBBAAAAAAAAAAAALcAAAACAAAAlQAAAAAAAAC3AAAAAQAAAJUAAAAAAAAA",
    "pkt_bounds_ok": "f0JQRgEBCgAAAAAAAAAAAGEWAAAAAAAAYRcEAAAAAAC/YgAAAAAAAAcCAAAOAAAALXIDAAAAAABxYwwAAAAAALcAAAACAAAAlQAAAAAAAAC3AAAAAQAAAJUAAAAAAAAA",
    "pkt_no_bounds": "f0JQRgEBBQAAAAAAAAAAAGEWAAAAAAAAYRcEAAAAAABxYwwAAAAAALcAAAACAAAAlQAAAAAAAAA=",
}


def parse_custom(b64):
    """Parse legacy custom binary format to extract raw components."""
    data = base64.b64decode(b64)
    prog_type = data[5]
    num_insns = struct.unpack("<H", data[6:8])[0]
    num_maps = data[8]
    off = 16
    maps_data = data[off:off + num_maps * 16]
    off += num_maps * 16
    insns_data = data[off:off + num_insns * 8]
    return prog_type, insns_data, maps_data


os.makedirs("/app/objects", exist_ok=True)
for name, b64 in PROGRAMS_B64.items():
    prog_type, insns, maps = parse_custom(b64)
    elf = make_bpf_elf(prog_type, insns, maps)
    with open(f"/app/objects/{name}.o", "wb") as f:
        f.write(elf)
