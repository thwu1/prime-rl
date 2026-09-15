A binary microcode ROM dump from the Intel 8086 processor's division unit is at `/app/microcode_rom.bin`. The encoding format is documented in `/app/rom_format.md`, algorithmic context is in `/app/division_context.md`, and a detailed microcode specification is in `/app/microcode_spec.md`.

Decode the ROM binary (a packed non-byte-aligned bitstream of 21-bit micro-instructions), reconstruct the microcode routines, and build a faithful division simulator. Validate your simulator against ground-truth results obtained from actual x86 hardware division instructions.

Produce the following files in `/app/`:

**`disassembly.txt`** — Human-readable disassembly of every routine in the ROM. Format each instruction as: `<line_number>: <src> -> <dst>  [<type>] <details>  <F if flag set>`. Use register and operation names from `rom_format.md`. Group instructions under routine headers.

**`simulator.py`** — Python module implementing the decoded microcode algorithm. Must export:
- `class DivisionOverflow(Exception)` — raised on divide-by-zero, quotient overflow, or the signed overflow quirk
- `execute_div(dividend_hi, dividend_lo, divisor, signed=False, byte_mode=False) -> (quotient, remainder)` — microcode-faithful division returning unsigned integer results

**`ground_truth.json`** — Division results obtained by writing x86-64 assembly test cases in NASM that execute actual `div` and `idiv` instructions on the reference test vectors from `division_context.md`, assembling them with `nasm`, linking with `ld`, running the resulting binary, and parsing the output. The JSON must have a `"test_vectors"` key containing an array of objects, each with keys: `"mode"` (`"word"`/`"byte"`), `"signed"` (bool), `"dx"` (int), `"ax"` (int), `"divisor"` (int), `"quotient"` (int), `"remainder"` (int). The NASM source file (`test_div.asm`) and assembled object/binary must also be present in `/app/`.