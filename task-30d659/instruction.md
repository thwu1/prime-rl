Unoptimized RISC-V Vector (RVV) assembly files are in `/app/input/`. Hand-optimized references for a subset are in `/app/reference/`. Reverse-engineer the applied optimizations from the input/reference pairs, then implement `/app/rvv_peephole.py` — a general peephole optimizer that reproduces those transformations across all inputs, including those without references.

**CLI interface:**

```
python3 /app/rvv_peephole.py <input.s>          # optimized assembly to stdout
python3 /app/rvv_peephole.py <input.s> --stats   # JSON with integer fields:
    # redundant_vsetvli_removed, fusions_applied, broadcast_instructions_removed
```

**Requirements:**
- Preserve all directives, labels, comments, and non-optimizable instructions exactly.
- Output must assemble without errors under `riscv64-linux-gnu-as -march=rv64gcv`.
- Handle all files in `/app/input/`, not only those with references.
- Respect negative cases in references — some apparently-optimizable patterns are intentionally preserved.

**Inputs:** `/app/input/input_basic.s`, `input_fusion.s`, `input_mixed.s`, `input_edge.s`
**References:** `/app/reference/reference_basic.s`, `reference_fusion.s`