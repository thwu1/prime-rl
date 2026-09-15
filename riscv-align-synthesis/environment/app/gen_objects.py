#!/usr/bin/env python3
"""Generate ROB (Relocatable Object Bundle) test scenario files.

This script runs during Docker build to create binary test inputs.
It is deleted after execution and not available to the solver.
"""

import struct
import os

MAGIC = b'ROB\x01'
V = 1

# Architecture codes (ELF e_machine)
RISCV = 243
LOONGARCH = 258

# Relocation types
R_RISCV_ALIGN = 36
R_LARCH_ALIGN = 102

# Relocation format flags
RELA = 0  # Has explicit addend
REL = 1   # No explicit addend


def write_rob(path, arch, sections, relocs=None):
    """
    Write a .rob binary file.

    sections: list of (name, size, addralign)
    relocs: list of (section_idx, r_offset, r_type, r_format, r_addend)
    """
    if relocs is None:
        relocs = []

    with open(path, 'wb') as f:
        # Header (16 bytes)
        f.write(MAGIC)
        f.write(struct.pack('<HHII', V, arch, len(sections), len(relocs)))

        # Section table (20 bytes each)
        for name, size, addralign in sections:
            name_bytes = name.encode('ascii')[:15]
            f.write(struct.pack('<B', len(name_bytes)))
            f.write(name_bytes.ljust(15, b'\x00'))
            f.write(struct.pack('<HH', size, addralign))

        # Relocation table (12 bytes each)
        for sec_idx, r_offset, r_type, r_fmt, r_addend in relocs:
            f.write(struct.pack('<HHHHi', sec_idx, r_offset, r_type, r_fmt, r_addend))


def main():
    d = '/app/objects'
    os.makedirs(d, exist_ok=True)

    # 1. RISC-V bare align=8 -- needs synthesis (addend=6)
    write_rob(f'{d}/riscv_bare_a8.rob', RISCV,
              [('.text', 16, 8)])

    # 2. LoongArch bare align=8 -- needs synthesis (addend=4)
    write_rob(f'{d}/la_bare_a8.rob', LOONGARCH,
              [('.text', 16, 8)])

    # 3. RISC-V strong ALIGN at offset 0 (addend=6 >= needed=6) -- suppressed
    write_rob(f'{d}/riscv_strong_a8.rob', RISCV,
              [('.text', 16, 8)],
              [(0, 0, R_RISCV_ALIGN, RELA, 6)])

    # 4. LoongArch strong ALIGN (addend=12 >= needed=12) -- suppressed
    write_rob(f'{d}/la_strong_a16.rob', LOONGARCH,
              [('.text', 16, 16)],
              [(0, 0, R_LARCH_ALIGN, RELA, 12)])

    # 5. RISC-V weak ALIGN (addend=2 < needed=6) -- must synthesize
    write_rob(f'{d}/riscv_weak_a8.rob', RISCV,
              [('.text', 16, 8)],
              [(0, 0, R_RISCV_ALIGN, RELA, 2)])

    # 6. LoongArch weak ALIGN (addend=4 < needed=12) -- must synthesize
    write_rob(f'{d}/la_weak_a16.rob', LOONGARCH,
              [('.text', 16, 16)],
              [(0, 0, R_LARCH_ALIGN, RELA, 4)])

    # 7. RISC-V REL format at offset 0 -- must synthesize (addend unknown)
    write_rob(f'{d}/riscv_rel_a8.rob', RISCV,
              [('.text', 16, 8)],
              [(0, 0, R_RISCV_ALIGN, REL, 0)])

    # 8. RISC-V at threshold (align=4 >= 4) -- needs synthesis (addend=2)
    write_rob(f'{d}/riscv_threshold_a4.rob', RISCV,
              [('.text', 8, 4)])

    # 9. RISC-V below threshold (align=2 < 4) -- no synthesis
    write_rob(f'{d}/riscv_below_a2.rob', RISCV,
              [('.text', 8, 2)])

    # 10. LoongArch at boundary (align=4, not > 4) -- no synthesis
    write_rob(f'{d}/la_boundary_a4.rob', LOONGARCH,
              [('.text', 8, 4)])

    # 11. RISC-V interior ALIGN at offset 16 (not 0) -- still needs boundary synthesis
    write_rob(f'{d}/riscv_interior_a8.rob', RISCV,
              [('.text', 32, 8)],
              [(0, 16, R_RISCV_ALIGN, RELA, 6)])

    # 12. RISC-V overstrong ALIGN (addend=14 > needed=6) -- still suppresses
    write_rob(f'{d}/riscv_overstrong_a8.rob', RISCV,
              [('.text', 16, 8)],
              [(0, 0, R_RISCV_ALIGN, RELA, 14)])

    # 13. RISC-V multi-section: .text.a align=4, .text.b align=8 with weak ALIGN
    write_rob(f'{d}/riscv_multi.rob', RISCV,
              [('.text.a', 16, 4), ('.text.b', 16, 8)],
              [(1, 0, R_RISCV_ALIGN, RELA, 2)])

    # 14. RISC-V borderline weak (addend=4, needed=6) -- must synthesize
    write_rob(f'{d}/riscv_borderline.rob', RISCV,
              [('.text', 16, 8)],
              [(0, 0, R_RISCV_ALIGN, RELA, 4)])

    # 15. LoongArch REL format at offset 0 -- must synthesize (addend unknown)
    write_rob(f'{d}/la_rel_a8.rob', LOONGARCH,
              [('.text', 16, 8)],
              [(0, 0, R_LARCH_ALIGN, REL, 0)])


if __name__ == '__main__':
    main()
