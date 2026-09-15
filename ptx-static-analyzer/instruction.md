Build `/app/ptx_analyzer.py` — a static analysis tool for NVIDIA PTX (Parallel Thread Execution) assembly. Given a PTX file, it outputs a JSON report to stdout characterizing the kernel's control flow graph, per-block register liveness, register pressure, and instruction-level parallelism.

```
python3 /app/ptx_analyzer.py <ptx_file>
```

Kernel inputs at `/app/kernels/`:
- `vecadd.ptx` — vector addition with conditional bounds-check
- `reduce.ptx` — sequential reduction with a loop
- `matmul.ll` — LLVM IR for a matrix multiply kernel (the LLVM nvptx64 backend is installed; compile to PTX before analysis)

## Output JSON

```json
{
  "kernel_name": "<from .visible .entry>",
  "num_basic_blocks": <int>,
  "cfg_edges": [["<source_block>", "<target_block>"], ...],
  "basic_blocks": {
    "<block_name>": {
      "num_instructions": <int>,
      "live_in": ["<sorted register names>"],
      "live_out": ["<sorted register names>"],
      "max_register_pressure": <int>,
      "critical_path_length": <int>,
      "ilp": <float>
    }
  }
}
```

**Metric definitions:**
- `live_in` / `live_out`: the set of registers whose values may be consumed before being redefined along some execution path from block entry / exit, respectively
- `max_register_pressure`: peak count of simultaneously live registers at any program point within the block
- `critical_path_length`: longest chain of data-dependent instructions within the block (counted in instructions, not cycles)
- `ilp`: `num_instructions / critical_path_length`

Track general-purpose registers (`%rN`, `%rdN`, `%fN`, `%fdN`, `%pN`); exclude built-in GPU registers (`%tid.*`, `%ctaid.*`, `%ntid.*`, and similar hardware read-only registers). The analysis must correctly handle PTX predicated execution (including negated predicates `@!%pN`), typed memory and ALU operations, cyclic control flow, and both hand-written PTX (explicit labels) and compiler-generated PTX from LLVM (unlabeled entry blocks, `$L__BB0_N` labels, `bra.uni` instructions, conditional+unconditional branch pairs).