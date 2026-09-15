"""
Section merging for ELF relocatable linking.

Coordinates the merging of multiple input sections into a single
output section, handling alignment padding and relocation synthesis
at each section boundary.
"""


from elf_defs import (
    Arch, InputSection, SynthesizedAlign, Relocation,
    get_align_type,
)
from synth_engine import synthesize_for_section


def align_up(value: int, alignment: int) -> int:
    """Round value up to the nearest multiple of alignment."""
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


def compute_output_alignment(sections: list) -> int:
    """
    Compute the output section alignment as the maximum of all
    input section alignments.
    """
    if not sections:
        return 1
    return max(sec.addralign for sec in sections)


def merge_sections(
    sections: list,
    arch: Arch,
    base_va: int = 0,
) -> dict:
    """
    Merge a list of input sections into a combined output section.

    For each section beyond the first, the running dot position is
    aligned to the section's addralign before processing. Then
    synthesize_for_section determines whether an ALIGN relocation
    must be emitted at the boundary.

    Args:
        sections: List of InputSection objects to merge
        arch:     Target architecture
        base_va:  Base virtual address (usually 0 for relocatable)

    Returns:
        Dict with keys:
          'synthesized':     List of SynthesizedAlign objects
          'relocated':       List of Relocation objects (offset-adjusted)
          'total_size':      Total output section size
          'section_offsets':  List of (name, offset) tuples
          'output_alignment': Maximum alignment across all sections
    """
    dot = base_va
    all_synthesized = []
    all_relocated = []
    section_offsets = []

    for i, sec in enumerate(sections):
        # Align dot for sections after the first
        if i > 0:
            dot = align_up(dot, sec.addralign)

        section_start = dot
        section_offsets.append((sec.name, section_start - base_va))

        # Run alignment synthesis for this section
        new_dot, synth = synthesize_for_section(dot, sec, arch, base_va)
        all_synthesized.extend(synth)

        # Copy existing relocations with offset adjusted to output position
        for rel in sec.relocations:
            adjusted = Relocation(
                r_offset=rel.r_offset + (section_start - base_va),
                r_type=rel.r_type,
                r_sym=rel.r_sym,
                r_addend=rel.r_addend,
            )
            all_relocated.append(adjusted)

        dot = new_dot

    return {
        'synthesized': all_synthesized,
        'relocated': all_relocated,
        'total_size': dot - base_va,
        'section_offsets': section_offsets,
        'output_alignment': compute_output_alignment(sections),
    }
