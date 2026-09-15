A MiniStack-16 stack-based virtual machine system is at `/app/`:

- `/app/spec.md` — ISA specification (partially complete; several instruction semantics are deliberately underspecified)
- `/app/assembler.py` — Assembler (`.asm` → `.bin` bytecode) — contains bugs
- `/app/emulator.c` — Emulator (executes `.bin` programs) — contains bugs
- `/app/Makefile` — Build system
- `/app/programs/*.bin` — Pre-compiled binary programs (compiled by a now-unavailable reference assembler; assembly source is not available)
- `/app/expected/*.txt` — Expected stdout for each program (ground truth)

The pre-compiled `.bin` files were produced by a reference implementation that is no longer available. The ISA specification has several areas where the semantics are **underspecified or ambiguous** — the spec alone is insufficient to determine the correct behavior for shifts, comparisons, and modular arithmetic. The pre-compiled binaries and their expected outputs constitute the **canonical behavioral specification** and must be used to resolve all ambiguities.

Both the current assembler and emulator contain multiple bugs. Some bugs relate to the underspecified areas (where the implementer chose the wrong interpretation), while others are conventional implementation errors in encoding or stack manipulation.

Your deliverables:

1. **`/app/semantics_report.json`** — Analyze the pre-compiled binaries against their expected outputs to resolve every ISA ambiguity. For each ambiguity, document: the instruction in question, the possible interpretations, which interpretation is correct, and the specific binary evidence that proves it. Format:
   ```json
   {"ambiguities": [{"instruction": "...", "question": "...", "resolution": "...", "evidence": "..."}, ...]}
   ```

2. **Fix all bugs** in `/app/assembler.py` and `/app/emulator.c` so that every program in `/app/programs/` produces output matching its corresponding file in `/app/expected/`. Use both the spec and your inferred semantics to determine correct behavior.

3. **`/app/disassembler.py`** — Implement a disassembler that converts `.bin` files back to assembly source. It must resolve jump/branch target offsets to symbolic labels and produce output that `assembler.py` can reassemble. Usage: `python3 disassembler.py <input.bin> <output.asm>`.

4. **`/app/optimizer.py`** — Design and implement a peephole optimizer for MiniStack-16 binaries. Usage: `python3 optimizer.py <input.bin> <output.bin>`. Requirements:
   - Constant folding: `PUSH X / PUSH Y / binop` → `PUSH result` for ADD, SUB, MUL
   - Identity elimination: `PUSH 0 / ADD` → remove, `PUSH 1 / MUL` → remove
   - Dead code removal: `PUSH X / POP` → remove
   - Must correctly handle jump targets — never optimize sequences that span basic block boundaries
   - Must recompute branch offsets after instructions are removed
   - Must preserve program semantics: optimized programs produce identical output to originals

5. **`/app/programs/selftest.asm`** — Write a comprehensive test program exercising all instruction categories (arithmetic, bitwise, shifts, comparisons, stack manipulation, memory access) with edge cases including the operations whose semantics you resolved. Each test prints its result with PUTI followed by a newline. When assembled and run, it must produce output matching `/app/expected/selftest.txt`.