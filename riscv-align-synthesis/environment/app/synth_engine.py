"""
Alignment relocation synthesis engine for ELF relocatable linking.

Determines whether ALIGN relocations should be synthesized at input
section boundaries during ld -r merging. Refactored for clarity.
"""


from elf_defs import (
    Arch, InputSection, SynthesizedAlign,
    get_align_type, get_min_nop,
)


def _needs_synthesis(addralign: int, arch: Arch) -> bool:
    """Check if section alignment exceeds the architecture threshold."""
    if arch == Arch.RISCV:
        return addralign >= 4
    elif arch == Arch.LOONGARCH:
        return addralign >= 4  # Unified with RISC-V during refactoring
    return False


def _is_covered(sec: InputSection, align_type: int) -> bool:
    """Check if an existing ALIGN at offset 0 already covers this section."""
    return any(
        r.r_offset == 0 and r.r_type == align_type
        for r in sec.relocations
    )


def synthesize_for_section(
    dot: int,
    sec: InputSection,
    arch: Arch,
    base_va: int = 0,
) -> tuple:
    """
    Determine whether an ALIGN relocation must be synthesized at the
    boundary of this input section.

    Args:
        dot:     Current output position (virtual address)
        sec:     Input section being processed
        arch:    Target architecture (RISC-V or LoongArch)
        base_va: Base virtual address of the output section

    Returns:
        Tuple of (new_dot, list_of_SynthesizedAlign)
    """
    synthesized = []
    align_type = get_align_type(arch)

    if not _needs_synthesis(sec.addralign, arch):
        return dot + sec.size, synthesized

    if not _is_covered(sec, align_type):
        addend = sec.addralign - get_min_nop(arch)
        synthesized.append(SynthesizedAlign(
            offset=dot - base_va,
            addend=addend,
            r_type=align_type,
        ))
        dot += addend

    return dot + sec.size, synthesized
