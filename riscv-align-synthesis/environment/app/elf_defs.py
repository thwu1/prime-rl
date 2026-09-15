"""
ELF type definitions for alignment relocation synthesis.

Provides data structures and constants for RISC-V and LoongArch
alignment relocation handling during relocatable linking.

Reference:
  - ELF Specification (Tool Interface Standard)
  - RISC-V ELF psABI Specification
  - LoongArch ELF psABI Specification
"""


from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List


class Arch(IntEnum):
    """ELF e_machine architecture identifiers."""
    RISCV = 243       # EM_RISCV
    LOONGARCH = 258   # EM_LOONGARCH


# ---- RISC-V relocation types (RISC-V ELF psABI) ----
R_RISCV_NONE = 0
R_RISCV_32 = 1
R_RISCV_64 = 2
R_RISCV_BRANCH = 16
R_RISCV_JAL = 17
R_RISCV_CALL = 18
R_RISCV_CALL_PLT = 19
R_RISCV_PCREL_HI20 = 23
R_RISCV_PCREL_LO12_I = 24
R_RISCV_HI20 = 26
R_RISCV_LO12_I = 27
R_RISCV_ALIGN = 36
R_RISCV_RELAX = 51
R_RISCV_SET6 = 53
R_RISCV_SUB6 = 54

# ---- LoongArch relocation types (LoongArch ELF psABI) ----
R_LARCH_NONE = 0
R_LARCH_32 = 1
R_LARCH_64 = 2
R_LARCH_B16 = 64
R_LARCH_B21 = 65
R_LARCH_B26 = 66
R_LARCH_PCALA_HI20 = 71
R_LARCH_PCALA_LO12 = 72
R_LARCH_ALIGN = 102
R_LARCH_RELAX = 103


@dataclass
class Relocation:
    """
    Represents an ELF relocation entry.

    For RELA sections (SHT_RELA, the default on RISC-V/LoongArch),
    r_addend holds the explicit addend value.

    For REL sections (SHT_REL, rare on these architectures), r_addend
    is None because the addend is stored implicitly within the
    instruction or data at the relocation site.

    In the context of R_RISCV_ALIGN / R_LARCH_ALIGN, the addend
    encodes the maximum padding (in bytes) that the assembler may
    have inserted at this alignment point. The final linker uses
    this to know how many NOP bytes it can remove during relaxation.
    """
    r_offset: int
    r_type: int
    r_sym: int = 0
    r_addend: Optional[int] = None

    @property
    def has_addend(self) -> bool:
        """Whether this relocation carries an explicit addend (RELA)."""
        return self.r_addend is not None

    def __repr__(self):
        parts = [f"off={self.r_offset:#x}", f"type={self.r_type}"]
        if self.has_addend:
            parts.append(f"addend={self.r_addend}")
        else:
            parts.append("REL")
        return f"Reloc({', '.join(parts)})"


@dataclass
class InputSection:
    """
    An input section from a relocatable ELF object file (.o).

    During relocatable linking (ld -r), multiple InputSections with
    the same output name are merged. The linker must handle alignment
    at section boundaries by synthesizing ALIGN relocations.
    """
    name: str
    size: int
    addralign: int
    relocations: List[Relocation] = field(default_factory=list)

    def __repr__(self):
        return (f"InputSection({self.name!r}, size={self.size}, "
                f"align={self.addralign}, nrels={len(self.relocations)})")


@dataclass
class SynthesizedAlign:
    """
    A synthesized alignment relocation produced during section merging.

    The offset is relative to the output section start.
    The addend represents the maximum padding bytes needed.
    """
    offset: int
    addend: int
    r_type: int

    def __repr__(self):
        return f"SynthAlign(off={self.offset:#x}, addend={self.addend})"


def get_align_type(arch: Arch) -> int:
    """Return the architecture-specific ALIGN relocation type."""
    _map = {
        Arch.RISCV: R_RISCV_ALIGN,
        Arch.LOONGARCH: R_LARCH_ALIGN,
    }
    if arch not in _map:
        raise ValueError(f"Unsupported architecture: {arch}")
    return _map[arch]


def get_min_nop(arch: Arch) -> int:
    """
    Return the minimum NOP instruction size in bytes.

    RISC-V (with C extension): c.nop = 2 bytes
    LoongArch:                  nop   = 4 bytes

    This determines the granularity of alignment padding:
    the synthesized addend is (section_alignment - min_nop).
    """
    _map = {
        Arch.RISCV: 2,
        Arch.LOONGARCH: 4,
    }
    if arch not in _map:
        raise ValueError(f"Unsupported architecture: {arch}")
    return _map[arch]


def get_relax_type(arch: Arch) -> int:
    """Return the architecture-specific RELAX relocation type."""
    _map = {
        Arch.RISCV: R_RISCV_RELAX,
        Arch.LOONGARCH: R_LARCH_RELAX,
    }
    if arch not in _map:
        raise ValueError(f"Unsupported architecture: {arch}")
    return _map[arch]
