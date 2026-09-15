#!/usr/bin/env python3
"""
Cpu0 Linker - reads ELF32 relocatable objects, resolves symbols and
relocations, and produces an ELF32 executable.
"""

import sys
import struct
import argparse

# ── ELF constants ──
ELFCLASS32 = 1
ELFDATA2MSB = 2
EV_CURRENT = 1
ELFOSABI_NONE = 0
ET_REL = 1
ET_EXEC = 2
EM_CPU0 = 0xC9

SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_REL = 9

SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4

PT_LOAD = 1
PF_R = 4
PF_X = 1

STB_LOCAL = 0
STB_GLOBAL = 1
SHN_UNDEF = 0

R_CPU0_PC24 = 1
R_CPU0_PC16 = 2
R_CPU0_32 = 3


def _get_str(strtab, offset):
    end = strtab.index(b"\0", offset)
    return strtab[offset:end].decode()


def read_object(path):
    with open(path, "rb") as f:
        data = f.read()

    assert data[0:4] == b"\x7fELF", f"{path}: not ELF"
    assert data[4] == ELFCLASS32 and data[5] == ELFDATA2MSB

    (e_type, e_machine, _, _, _, e_shoff, _, _, _, _,
     e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(">HHIIIIIHHHHHH", data, 16)
    assert e_type == ET_REL, f"{path}: not relocatable"
    assert e_machine == EM_CPU0, f"{path}: wrong machine"

    # Parse section headers
    secs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
         sh_link, sh_info, sh_addralign, sh_entsize) = struct.unpack_from(">IIIIIIIIII", data, off)
        sec_data = data[sh_offset:sh_offset + sh_size] if sh_type != SHT_NULL else b""
        secs.append({"name_off": sh_name, "type": sh_type, "data": sec_data,
                      "link": sh_link, "info": sh_info, "entsize": sh_entsize})

    shstrtab = secs[e_shstrndx]["data"]
    for s in secs:
        s["name"] = _get_str(shstrtab, s["name_off"])

    # Extract key sections
    text_data = b""
    symtab_data = b""
    strtab_data = b""
    rel_data = b""
    symtab_link = 0

    for s in secs:
        if s["name"] == ".text":
            text_data = s["data"]
        elif s["name"] == ".symtab":
            symtab_data = s["data"]
            symtab_link = s["link"]
        elif s["name"] == ".rel.text":
            rel_data = s["data"]

    if symtab_link > 0:
        strtab_data = secs[symtab_link]["data"]

    # Parse symbols
    symbols = []
    for i in range(len(symtab_data) // 16):
        st_name, st_value, st_size, st_info, st_other, st_shndx = \
            struct.unpack_from(">IIIBBH", symtab_data, i * 16)
        symbols.append({
            "name": _get_str(strtab_data, st_name) if st_name > 0 else "",
            "value": st_value,
            "binding": (st_info >> 4) & 0xF,
            "shndx": st_shndx,
        })

    # Parse relocations
    relocs = []
    for i in range(len(rel_data) // 8):
        r_offset, r_info = struct.unpack_from(">II", rel_data, i * 8)
        sym_idx = r_info >> 8
        rtype = r_info & 0xFF
        relocs.append({
            "offset": r_offset,
            "type": rtype,
            "sym_idx": sym_idx,
            "sym_name": symbols[sym_idx]["name"] if sym_idx < len(symbols) else "",
        })

    return {"text": bytearray(text_data), "symbols": symbols, "relocs": relocs}


def link(input_paths, output_path):
    objects = [read_object(p) for p in input_paths]

    # Phase 1: merge .text sections
    merged = bytearray()
    bases = []
    for obj in objects:
        bases.append(len(merged))
        merged += obj["text"]

    # Phase 2: build global symbol table
    gsyms = {}
    for i, obj in enumerate(objects):
        for sym in obj["symbols"]:
            if sym["binding"] == STB_GLOBAL and sym["shndx"] != SHN_UNDEF and sym["name"]:
                if sym["name"] in gsyms:
                    raise ValueError(f"Duplicate symbol: {sym['name']}")
                gsyms[sym["name"]] = bases[i] + sym["value"]

    # Phase 3: process relocations
    for i, obj in enumerate(objects):
        base = bases[i]
        for rel in obj["relocs"]:
            sym = obj["symbols"][rel["sym_idx"]] if rel["sym_idx"] < len(obj["symbols"]) else None

            # Resolve target address
            if sym and sym["shndx"] != SHN_UNDEF and sym["name"]:
                target = base + sym["value"]
            elif rel["sym_name"] in gsyms:
                target = gsyms[rel["sym_name"]]
            else:
                raise ValueError(f"Undefined symbol: {rel['sym_name']}")

            patch_off = base + rel["offset"]
            word = struct.unpack_from(">I", merged, patch_off)[0]

            if rel["type"] == R_CPU0_PC24:
                disp = target - (patch_off + 4)
                word = (word & 0xFF000000) | (disp & 0x00FFFFFF)
            elif rel["type"] == R_CPU0_PC16:
                disp = target - (patch_off + 4)
                word = (word & 0xFFFF0000) | (disp & 0x0000FFFF)
            elif rel["type"] == R_CPU0_32:
                word = target & 0xFFFFFFFF

            struct.pack_into(">I", merged, patch_off, word)

    # Find entry point
    if "_start" not in gsyms:
        raise ValueError("No _start symbol")
    entry = gsyms["_start"]

    _write_exec(output_path, merged, entry)


def _align(v, a):
    return (v + a - 1) & ~(a - 1)


def _write_exec(path, text_data, entry):
    ELF_HDR = 52
    PHDR_SZ = 32
    text_off = ELF_HDR + PHDR_SZ
    text_sz = len(text_data)

    shstrtab = b"\0.text\0.shstrtab\0"
    shstrtab_off = text_off + text_sz
    shoff = _align(shstrtab_off + len(shstrtab), 4)

    with open(path, "wb") as f:
        # ELF header
        ident = bytearray(16)
        ident[0:4] = b"\x7fELF"
        ident[4] = ELFCLASS32; ident[5] = ELFDATA2MSB; ident[6] = EV_CURRENT
        f.write(bytes(ident))
        f.write(struct.pack(">HHIIIIIHHHHHH",
            ET_EXEC, EM_CPU0, EV_CURRENT, entry,
            ELF_HDR, shoff, 0, ELF_HDR,
            PHDR_SZ, 1, 40, 3, 2))

        # Program header (PT_LOAD)
        f.write(struct.pack(">IIIIIIII",
            PT_LOAD, text_off, 0, 0, text_sz, text_sz,
            PF_R | PF_X, 4))

        # .text
        f.write(text_data)

        # .shstrtab
        f.write(shstrtab)

        # Pad to section headers
        pos = f.tell()
        if shoff > pos:
            f.write(b"\0" * (shoff - pos))

        # Section headers: NULL, .text, .shstrtab
        f.write(struct.pack(">IIIIIIIIII", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        f.write(struct.pack(">IIIIIIIIII",
            1, SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, 0,
            text_off, text_sz, 0, 0, 4, 0))
        f.write(struct.pack(">IIIIIIIIII",
            7, SHT_STRTAB, 0, 0,
            shstrtab_off, len(shstrtab), 0, 0, 1, 0))


def main():
    p = argparse.ArgumentParser(description="Cpu0 Linker")
    p.add_argument("-o", required=True, help="Output executable")
    p.add_argument("inputs", nargs="+", help="Input .o files")
    args = p.parse_args()
    link(args.inputs, args.o)


if __name__ == "__main__":
    main()
