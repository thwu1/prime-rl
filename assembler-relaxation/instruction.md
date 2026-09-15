Implement `/app/relax.py` — a full assembler for the simplified ISA defined in `/app/isa_spec.md`.

The program must support two modes:

- `python3 /app/relax.py <input.asm>` — outputs JSON to stdout: `{"labels": {"name": offset, ...}, "total_size": N}`
- `python3 /app/relax.py -b <input.asm> -o <output.bin>` — writes assembled raw machine code bytes to the output file

Jump instructions have variable-width encodings (short and long forms with different byte sizes, and the long-form size differs between unconditional and conditional jumps). The assembler must produce a layout where every jump uses its smallest valid encoding — a jump may only use the short form if its PC-relative displacement fits within the signed 8-bit range given the final layout, and the layout must be globally self-consistent. Alignment directives (`.align N`) produce position-dependent padding that interacts with encoding choices.

The binary output must contain correctly encoded opcode bytes for every instruction. The ISA spec documents instruction sizes and some opcode values, but intentionally omits others. A compiled reference assembler is available at `/app/reference_asm` (run with `-h` for usage). It supports multiple output modes — JSON label maps, raw binary file output, hex dumps, and label position listings. Use these modes together with `xxd`, `cmp`, `diff`, and other binary analysis tools to reverse-engineer the complete opcode encoding scheme and validate your implementation byte-for-byte. Sample assembly files are in `/app/samples/`. Your solution must produce identical output to the reference on all valid inputs.