Four computational kernels are provided as C source files in `/app/kernels/`:

- `saxpy.c` — SAXPY vector operation
- `matmul.c` — Dense 64×64 matrix multiply (single precision)
- `poly_eval.c` — Horner polynomial evaluation over point arrays
- `stencil.c` — 1-D 3-point weighted stencil

A RISC-V 64-bit cross-compilation toolchain is available: `riscv64-linux-gnu-gcc`, `riscv64-linux-gnu-objdump`, and `qemu-riscv64`.

Audit the code that GCC generates for these kernels across two RISC-V targets, identify codegen inefficiencies, and produce optimized vectorized replacements that exploit the RISC-V Vector Extension.

## Deliverables

### Optimized kernel sources

Create the following files:

- `/app/optimized/saxpy_opt.c`
- `/app/optimized/matmul_opt.c`
- `/app/optimized/poly_eval_opt.c`
- `/app/optimized/stencil_opt.c`

Each file must be a self-contained C program with a `main()` function that:

- Compiles successfully with: `riscv64-linux-gnu-gcc -static -O2 -march=rv64gcv -mabi=lp64d <source> -o <output> -lm`
- Produces output identical to the corresponding reference kernel (compiled with `-static -O2 -march=rv64gc -mabi=lp64d`) when both are executed via: `qemu-riscv64 -cpu rv64,v=true,vlen=256 <binary>`
- Contains RISC-V Vector Extension (RVV) instructions in the compiled binary (verifiable via `riscv64-linux-gnu-objdump -d`)

### Analysis report — `/app/analysis.json`

A JSON file conforming to the following schema:

```json
{
  "kernels": {
    "<kernel_name>": {
      "gcc_scalar": {
        "instruction_count": "<positive integer>"
      },
      "gcc_vector": {
        "instruction_count": "<positive integer>"
      }
    }
  },
  "optimization_categories": [
    {
      "category": "<category_id>",
      "description": "<string, more than 10 characters>",
      "affected_kernels": ["<kernel_name>", "..."]
    }
  ],
  "summary": {
    "total_categories_found": "<integer, at least 3>"
  }
}
```

Field specifications:

- **`kernels`**: Must contain an entry for each of the four kernels (`saxpy`, `matmul`, `poly_eval`, `stencil`). Each entry must have `gcc_scalar` and `gcc_vector` sub-objects, each containing `instruction_count` — a positive integer representing the number of instructions in the kernel function when compiled with `-static -O2 -march=rv64gc -mabi=lp64d` (scalar) or `-static -O2 -march=rv64gcv -mabi=lp64d` (vector).

- **`optimization_categories`**: A list with at least 3 entries. Each entry must contain:
  - `category` — one of the following identifiers: `missed_unrolling`, `redundant_moves`, `register_pressure`, `missing_vectorization`, `addressing_overhead`, `branch_overhead`, `constant_materialization`, `suboptimal_scheduling`, `spill_fill`, `missed_fusion`, `inefficient_prologue_epilogue`
  - `description` — a string longer than 10 characters explaining the inefficiency
  - `affected_kernels` — a non-empty list of kernel names affected by this inefficiency

- **`summary`**: Must contain `total_categories_found` as an integer ≥ 3.

### Build script — `/app/build.sh`

An executable shell script (must have the execute permission bit set).