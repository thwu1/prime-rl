"""
ROB (Relocatable Object Bundle) binary file parser.

Reads .rob binary files and returns structured section/relocation data.
See /app/rob_format.md for the binary format specification.
"""


import struct
from elf_defs import Arch, Relocation, InputSection

ROB_MAGIC = b'ROB\x01'


def parse_rob_file(path: str) -> dict:
    """
    Parse a .rob binary file and return its contents.

    Returns a dict with:
        'arch': Arch enum value (Arch.RISCV or Arch.LOONGARCH)
        'sections': list of InputSection objects (with relocations attached)

    Raises ValueError on invalid magic or unsupported version.
    """
    with open(path, 'rb') as f:
        data = f.read()

    # Validate magic
    if data[:4] != ROB_MAGIC:
        raise ValueError(
            f"Invalid ROB magic: {data[:4]!r}, expected {ROB_MAGIC!r}")

    # Parse 16-byte header
    version, arch_val, sec_count, rel_count = struct.unpack_from(
        '<HHII', data, 4)

    if version != 1:
        raise ValueError(f"Unsupported ROB version: {version}")

    arch = Arch(arch_val)

    # Parse section table (20 bytes per entry)
    sections = []
    pos = 16
    for _ in range(sec_count):
        name_len = data[pos]
        name = data[pos + 1:pos + 1 + name_len].decode('ascii')
        sec_size, addralign = struct.unpack_from('<HH', data, pos + 16)
        sections.append(InputSection(
            name=name, size=sec_size, addralign=addralign))
        pos += 20

    # Parse relocation table (12 bytes per entry)
    for _ in range(rel_count):
        sec_idx, r_offset, r_type, r_format, r_addend = struct.unpack_from(
            '<HHHHi', data, pos)

        rel = Relocation(
            r_offset=r_offset,
            r_type=r_type,
            r_addend=r_addend,
        )

        if 0 <= sec_idx < len(sections):
            sections[sec_idx].relocations.append(rel)
        pos += 12

    return {'arch': arch, 'sections': sections}
