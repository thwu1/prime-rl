#!/usr/bin/env python3
"""Implement ROB parser and synthesis engine."""


PARSER_CODE = '''import struct
from elf_defs import Arch, Relocation, InputSection

ROB_MAGIC = b'ROB\\x01'


def parse_rob_file(path):
    """Parse a .rob binary file."""
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 16 or data[:4] != ROB_MAGIC:
        raise ValueError(f"Invalid ROB magic: {data[:4]!r}")

    version, arch_code, nsec, nrel = struct.unpack_from('<HHII', data, 4)
    if version != 1:
        raise ValueError(f"Unsupported ROB version: {version}")

    arch = Arch(arch_code)
    sections = []
    offset = 16

    for _ in range(nsec):
        name_len = data[offset]
        offset += 1
        name = data[offset:offset + name_len].decode('ascii')
        offset += 15
        size, addralign = struct.unpack_from('<HH', data, offset)
        offset += 4
        sections.append(InputSection(name, size, addralign))

    for _ in range(nrel):
        sec_idx, r_offset, r_type, r_fmt = struct.unpack_from('<HHHH', data, offset)
        offset += 8
        r_addend_raw = struct.unpack_from('<i', data, offset)[0]
        offset += 4
        r_addend = r_addend_raw if r_fmt == 0 else None
        rel = Relocation(r_offset=r_offset, r_type=r_type, r_addend=r_addend)
        sections[sec_idx].relocations.append(rel)

    return {\'arch\': arch, \'sections\': sections}
'''

ENGINE_CODE = '''from elf_defs import (
    Arch, InputSection, SynthesizedAlign,
    get_align_type, get_min_nop,
)


def _exceeds_threshold(addralign, arch):
    """Check if alignment exceeds the architecture-specific synthesis threshold."""
    if arch == Arch.RISCV:
        return addralign >= 4
    elif arch == Arch.LOONGARCH:
        return addralign > 4
    return False


def _is_covered(sec, align_type, arch):
    """Check if an existing ALIGN at offset 0 sufficiently covers alignment need."""
    needed = sec.addralign - get_min_nop(arch)
    for r in sec.relocations:
        if r.r_offset != 0 or r.r_type != align_type:
            continue
        if not r.has_addend:
            continue
        if r.r_addend >= needed:
            return True
    return False


def synthesize_for_section(dot, sec, arch, base_va=0):
    """Synthesize ALIGN relocations for a section boundary."""
    synthesized = []
    align_type = get_align_type(arch)

    if not _exceeds_threshold(sec.addralign, arch):
        dot += sec.size
        return dot, synthesized

    if not _is_covered(sec, align_type, arch):
        addend = sec.addralign - get_min_nop(arch)
        synthesized.append(SynthesizedAlign(
            offset=dot - base_va,
            addend=addend,
            r_type=align_type,
        ))
        dot += addend

    dot += sec.size
    return dot, synthesized
'''

with open('/app/rob_parser.py', 'w') as f:
    f.write(PARSER_CODE)

with open('/app/synth_engine.py', 'w') as f:
    f.write(ENGINE_CODE)

print("Implemented rob_parser.py and synth_engine.py successfully.")
