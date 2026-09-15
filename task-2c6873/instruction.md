Build a complete ELF-based toolchain for the Cpu0 32-bit RISC architecture: an assembler emitting ELF32 relocatable object files, a linker that resolves cross-module symbols and relocations to produce ELF executables, and a simulator that loads and executes those executables.

The ISA specification is at `/app/spec/cpu0_isa.md`. It defines the full instruction set (50+ instructions across three encoding formats), register file, Cpu0-specific ELF conventions (machine type EM_CPU0 = 0xC9), relocation types (R_CPU0_PC24, R_CPU0_PC16, R_CPU0_32), symbol table requirements, and the linking/execution model.

Assembly programs are in `/app/programs/`. Single-file programs (`arith.s`, `factorial.s`, `gcd.s`) test the basic assemble-link-simulate pipeline. Multi-file programs (`main.s` calling functions from `mathlib.s` and `utils.s` via `JSUB`) test cross-module symbol resolution and relocation patching.

Create three executables:

- `/app/cpu0asm` — Assembler. Reads `.s` source, produces an ELF32 big-endian relocatable object file (`.o`) with correct ELF/section headers, `.text` section, symbol table (local/global binding, undefined externals), string tables, and `.rel.text` entries for unresolved references. The output must be parseable by the system `readelf` utility.

- `/app/cpu0ld` — Linker. Invoked as `/app/cpu0ld -o <output> <input.o> [...]`. Merges `.text` sections in input order, resolves all global symbols, processes relocation entries (patching PC-relative offsets for JSUB calls, etc.), and emits an ELF32 executable with a PT_LOAD program header and entry point at `_start`.

- `/app/cpu0sim` — Simulator. Loads an ELF executable by parsing its program headers, sets PC to the ELF entry point, initializes CPU state per the spec, executes the Cpu0 program, and prints final register values.