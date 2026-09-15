Three tools at `/app/src/` process BCVF bytecode programs. The opcode specification at `/app/src/opcode_def.h` defines instruction encoding, stack effects, and operand formats and is the authoritative reference for all tools.

**Binary format** (all little-endian): 4-byte magic `BCVF`, u16 `num_locals`, u16 `num_args`, u32 `code_len`, then `code_len` bytes of instructions. Branch offsets (if_false, if_true, goto_op, catch) are signed 32-bit, relative to the branch instruction's own start address. The `call` instruction carries a u16 arg_count operand and pops (arg_count + 1) values.

**Disassembler** (`./bcdump <file.bc>`): prints a header comment, one line per instruction, and a summary. Per-instruction format:

    OFFSET: OPNAME
    OFFSET: OPNAME OPERAND
    OFFSET: OPNAME OPERAND -> TARGET

OFFSET is the decimal byte offset, OPERAND is the decoded decimal operand value, and TARGET is the resolved absolute byte address for branch/catch instructions. Summary line: `; SUMMARY instructions=N code_bytes=N`. Size-3 instructions have u16 operands printed as unsigned decimal; size-5 non-branch instructions have i32/u32 operands printed as signed decimal; size-5 branch instructions print both the signed relative offset and the resolved absolute target. The skeleton at `/app/src/bcdump.c` has operand decoding and target resolution defects.

**Verifier** (`./verifier <file.bc>`): performs abstract stack interpretation and prints `RESULT: VALID` with `MAX_STACK` and per-instruction depths, or `RESULT: INVALID` with error messages. The implementation contains correctness defects affecting stack-effect metadata and control-flow depth propagation.

**Optimizer** (`./optimizer <input.bc> <output.bc>`): reads a BCVF file and writes a semantically equivalent file with reduced code size. The skeleton at `/app/src/optimizer.c` provides data structures, binary I/O, and stub optimization functions that return zero. Each stub's name and signature indicate its purpose. Optimization must iterate until a fixpoint. After all passes, deleted instructions must be removed and all branch offsets recomputed for new positions.

Do not modify `/app/src/opcode_def.h` or `/app/src/Makefile`. Build with `make -C /app/src`.

**Success criteria**: `make -C /app/src` compiles all three tools without errors. The disassembler correctly decodes all operands and resolves branch targets to absolute addresses. The verifier correctly performs abstract stack interpretation per the opcode specification. The optimizer produces output that passes the corrected verifier with correct `MAX_STACK` and per-instruction depths, and reduces code size where optimizations apply.
