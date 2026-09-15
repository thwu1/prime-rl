#!/usr/bin/env python3
"""Generate hidden BPF ELF object files for testing."""
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
    """Create a BPF ELF relocatable object file."""
    has_maps = len(maps_data) > 0
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

    off = 64
    text_off = off
    off += len(insns_data)
    if has_maps:
        maps_off = off
        off += len(maps_data)
    meta_off = off
    off += len(meta_data)
    strtab_off = off
    off += len(shstrtab)
    shdr_off = (off + 7) & ~7
    num_sh = 4 + (1 if has_maps else 0)
    shstrndx = num_sh - 1

    e_ident = bytes([0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 0, 0,0,0,0,0,0,0,0])
    ehdr = e_ident + struct.pack("<HHIQQQIHHHHHH",
        1, 247, 1, 0, 0, shdr_off, 0, 64, 0, 0, 64, num_sh, shstrndx)

    blob = bytearray(ehdr)
    blob += insns_data
    if has_maps:
        blob += maps_data
    blob += meta_data
    blob += shstrtab
    blob += b"\x00" * (shdr_off - len(blob))

    def shdr(name, typ, flags, offset, size, align):
        return struct.pack("<IIQQQQIIQQ", name, typ, flags, 0, offset, size, 0, 0, align, 0)

    blob += shdr(0, SHT_NULL, 0, 0, 0, 0)
    blob += shdr(name_text, SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR,
                 text_off, len(insns_data), 8)
    if has_maps:
        blob += shdr(name_maps, SHT_PROGBITS, SHF_ALLOC,
                     maps_off, len(maps_data), 4)
    blob += shdr(name_meta, SHT_PROGBITS, 0, meta_off, len(meta_data), 1)
    blob += shdr(name_shstrtab, SHT_STRTAB, 0, strtab_off, len(shstrtab), 1)
    return bytes(blob)


PROGRAMS_B64 = {
    "combined_valid":    "f0JQRgEBFAABAAAAAAAAAAAAAAABAAAABAAAAAgAAABhFgAAAAAAAGEXBAAAAAAAvxgAAAAAAAC/YgAAAAAAAAcCAAAUAAAALXIMAAAAAABxaQkAAAAAAGOa/P8AAAAAv6IAAAAAAAAHAgAA/P///7cBAAAAAAAAhQAAAAEAAAAVAAMAAAAAAGEBAAAAAAAAFQEBAAAAAAAFAAIAAAAAALcAAAACAAAAlQAAAAAAAAC3AAAAAQAAAJUAAAAAAAAA",
    "no_exit":           "f0JQRgEBBAAAAAAAAAAAALcGAAAFAAAAFQYBAAUAAACVAAAAAAAAALcAAAACAAAA",
    "null_wrong_branch": "f0JQRgEBCwABAAAAAAAAAAAAAAABAAAABAAAAAgAAABiCvz/AAAAAL+iAAAAAAAABwIAAPz///+3AQAAAAAAAIUAAAABAAAAVQADAAAAAABhAQAAAAAAALcAAAABAAAAlQAAAAAAAAC3AAAAAgAAAJUAAAAAAAAA",
    "uninit_in_branch":  "f0JQRgEBBQAAAAAAAAAAALcGAAABAAAAFQYBAAEAAAC3BwAAKgAAAL9wAAAAAAAAlQAAAAAAAAA=",
}


def parse_custom(b64):
    data = base64.b64decode(b64)
    prog_type = data[5]
    num_insns = struct.unpack("<H", data[6:8])[0]
    num_maps = data[8]
    off = 16
    maps_data = data[off:off + num_maps * 16]
    off += num_maps * 16
    insns_data = data[off:off + num_insns * 8]
    return prog_type, insns_data, maps_data


os.makedirs("/tmp/extra_objects", exist_ok=True)
for name, b64 in PROGRAMS_B64.items():
    prog_type, insns, maps = parse_custom(b64)
    elf = make_bpf_elf(prog_type, insns, maps)
    with open(f"/tmp/extra_objects/{name}.o", "wb") as f:
        f.write(elf)
