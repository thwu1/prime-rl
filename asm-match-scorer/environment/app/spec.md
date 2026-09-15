# Assembly Function Match Scorer — Specification

## Overview

This tool compares two x86-64 ELF relocatable object files (`.o`), each containing a single
assembly function, and produces a similarity score. A score of 0 indicates the functions are
identical modulo register assignment; higher scores indicate greater divergence.

## Interface

**Command:**
```
python3 /app/scorer.py <target.o> <candidate.o>
```

**Output:** JSON to stdout with these fields:
- `score` (int): Non-negative match score. 0 = perfect match after optimal register renaming.
- `num_target` (int): Number of instructions in the disassembled target function.
- `num_candidate` (int): Number of instructions in the disassembled candidate function.
- `register_mapping` (dict): Applied register renamings as `{"%source": "%dest", ...}`. Only include non-identity entries. Must be bijective.

## Register Families

x86-64 has 16 general-purpose register families. Each family shares a physical register
accessed at different widths:

| Family | 64-bit | 32-bit | 16-bit | 8-bit low | 8-bit high |
|--------|--------|--------|--------|-----------|------------|
| rax    | %rax   | %eax   | %ax    | %al       | %ah        |
| rbx    | %rbx   | %ebx   | %bx    | %bl       | %bh        |
| rcx    | %rcx   | %ecx   | %cx    | %cl       | %ch        |
| rdx    | %rdx   | %edx   | %dx    | %dl       | %dh        |
| rsi    | %rsi   | %esi   | %si    | %sil      | —          |
| rdi    | %rdi   | %edi   | %di    | %dil      | —          |
| rbp    | %rbp   | %ebp   | %bp    | %bpl      | —          |
| rsp    | %rsp   | %esp   | %sp    | %spl      | —          |
| r8–r15 | %rN    | %rNd   | %rNw   | %rNb      | —          |

When renaming register family A to family B, **all** width variants in the function must be
renamed consistently. For example, renaming the `rbx` family to `rcx` means `%rbx`→`%rcx`,
`%ebx`→`%ecx`, `%bx`→`%cx`, `%bl`→`%cl`, `%bh`→`%ch`.

## Register Renaming

The scorer must find the register-to-register mapping (bijection on families) that minimizes
the alignment score. This is a combinatorial optimization problem.

**Cyclic mappings** must be handled correctly. For example, if the target uses `%ebx`, `%ecx`,
`%edx` and the candidate uses a cyclic permutation `%ecx`, `%edx`, `%ebx`, the optimal
mapping `ebx→ecx, ecx→edx, edx→ebx` must produce score 0. Applying register substitutions
sequentially (one at a time) corrupts cyclic mappings — simultaneous substitution is required.

## Sequence Alignment

Functions may have different numbers of instructions. Use global sequence alignment
(e.g., Needleman-Wunsch) to find the best correspondence between instruction sequences.

**Scoring guidance:**
- Matching instructions (after register renaming): cost 0
- Gap (instruction present in one sequence but not the other): positive penalty
- Mismatched mnemonic: higher penalty than operand difference
- Mismatched operand: smaller penalty per differing operand

Exact penalty values are up to the implementation, but they must produce correct rankings
(equivalent functions score 0; more different functions score higher).

## Available System Tools

The environment includes standard Linux utilities for binary analysis:
`gcc`, `as`, `objdump`, `readelf`, `nm`, `python3`.

## Sample Data

Sample `.o` files are in `/app/objects/` for development and testing. These include pairs
of object files representing identical functions, register-renamed variants, and
modified functions.
