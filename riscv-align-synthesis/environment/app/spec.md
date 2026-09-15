# ELF Alignment Relocation Synthesis Specification

## Background

When the ELF linker operates in relocatable mode (`ld -r`), it merges input
sections from multiple object files into combined output sections. At each
input section boundary within the merged output, alignment padding may be
required. The linker synthesizes architecture-specific alignment relocations
(`R_RISCV_ALIGN` or `R_LARCH_ALIGN`) at these boundaries so the final link
step can correctly handle alignment during linker relaxation.

The synthesized relocation's addend encodes the maximum number of NOP padding
bytes the final linker may need to insert or remove at that boundary.

## Architecture-Specific Rules

### RISC-V

- **Synthesis threshold**: `addralign >= 4`
- **Minimum NOP size**: 2 bytes (`c.nop` with compressed extension)
- **Relocation type**: `R_RISCV_ALIGN` (type 36)
- **Synthesis addend**: `addralign - 2`

### LoongArch

- **Synthesis threshold**: `addralign > 4`
- **Minimum NOP size**: 4 bytes (`nop`)
- **Relocation type**: `R_LARCH_ALIGN` (type 102)
- **Synthesis addend**: `addralign - 4`

**Why the asymmetry?** RISC-V uses `>=` because compressed NOPs are only 2
bytes, so even 4-byte alignment may require NOP padding during relaxation.
LoongArch uses `>` because its minimum NOP is already 4 bytes, making 4-byte
alignment trivially satisfied without extra padding.

## The Suppression Question

Some input sections already carry ALIGN relocations at offset 0, emitted by
the assembler. When the linker encounters such a relocation, it must decide
whether to suppress its own synthesis at that section boundary.

### Approach A: Existence Check

If any ALIGN relocation of the correct type exists at offset 0, suppress
synthesis. Rationale: the assembler already emitted alignment handling at
the section entry point.

### Approach B: Strength-Aware Check

Only suppress synthesis if an ALIGN relocation at offset 0 has an addend
value that is **greater than or equal to** the section's alignment
requirement minus the minimum NOP size (`addralign - min_nop`). If the
existing addend is weaker than what the section's alignment demands,
proceed with synthesis anyway.

### A Concrete Scenario

Consider assembly source processed by an older GNU assembler:

```asm
.balign 4           ; produces R_RISCV_ALIGN with addend=2
.option norelax
.balign 8           ; produces NO relocation (relaxation disabled)
```

The resulting object file has section `addralign = 8` (from the `.balign 8`)
but carries only an `R_RISCV_ALIGN` with addend = 2 at offset 0
(from `.balign 4`). The `.balign 8` under `.option norelax` emits no
relocation because it does not participate in relaxation.

Under Approach A, the existing weak ALIGN would suppress synthesis, leaving
the section without adequate alignment coverage during the final link.
Under Approach B, the weak addend (2 < needed 6) would not suppress, and
the correct stronger ALIGN would be synthesized.

Modern LLVM assembler avoids emitting redundant weak ALIGNs, making both
approaches equivalent for new toolchain output. However, relocatable objects
from older assemblers (and current GNU assembler as of mid-2026) may contain
these weak ALIGNs.

## REL vs RELA Format

ELF defines two relocation formats:

- **RELA** (`SHT_RELA`): Each entry contains an explicit `r_addend` field.
  The addend can be examined to determine alignment strength.
- **REL** (`SHT_REL`): No explicit addend field. The addend is stored
  implicitly in the instruction or data at the relocation site and cannot be
  determined from the relocation entry alone.

When an ALIGN relocation at offset 0 is in REL format, the alignment
strength encoded in the addend is not accessible from the relocation table.
Your implementation must account for this ambiguity.

## Interior Relocations

ALIGN relocations at non-zero offsets within a section are interior alignment
points. They do not affect the synthesis decision at the section boundary
(offset 0). Only ALIGN relocations at offset 0 are relevant for the
suppression check.

## Implementation Interface

Your `synthesize_for_section(dot, sec, arch, base_va=0)` function receives:

- `dot`: current output position (virtual address offset)
- `sec`: an `InputSection` with `.name`, `.size`, `.addralign`, and
  `.relocations` (list of `Relocation` objects)
- `arch`: `Arch.RISCV` or `Arch.LOONGARCH`
- `base_va`: base virtual address of the output section

It must return `(new_dot, list_of_SynthesizedAlign)` where:

- `new_dot = dot + (addend if synthesized else 0) + sec.size`
- Each `SynthesizedAlign` has `offset = dot - base_va`, the computed addend,
  and the architecture-appropriate relocation type

Use the helper functions in `elf_defs.py`:
- `get_align_type(arch)` returns the relocation type constant
- `get_min_nop(arch)` returns the minimum NOP size in bytes
