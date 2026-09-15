Seven LLVM IR benchmark programs are at `/app/benchmarks/` (compiled from C at `-O0` without `optnone`). The LLVM 18 toolchain is installed (`opt`, `clang`). Use `/app/count_ir.py` for deterministic instruction counting (`python3 /app/count_ir.py <file.ll>`). Discover available passes via `opt --print-passes`.

Build an optimization system that discovers custom `opt` pass sequences minimizing IR instruction count beyond `-Oz` for each benchmark. Pipeline shorthands (`default<O2>`, `O3`, etc.) are prohibited — only individual new-PM pass names in `opt -passes='p1,p2,...'` syntax.

Two deliverables:

1. **Per-benchmark sequences**: A custom pass sequence for each benchmark that beats `-Oz`. Each sequence may contain at most 25 passes.

2. **Universal sequence**: A single pass sequence (at most 25 passes) that improves over `-Oz` on average across all 7 benchmarks and does not regress (increase instruction count vs. `-Oz`) on any individual benchmark.

Write results to `/app/results.json`:

    {
      "benchmarks": {
        "<name>": {
          "pass_sequence": ["pass1", "pass2", ...],
          "optimized_count": <int>,
          "oz_count": <int>,
          "improvement_pct": <float>
        }
      },
      "universal": {
        "pass_sequence": ["pass1", ...],
        "results": {
          "<name>": {
            "optimized_count": <int>,
            "oz_count": <int>,
            "improvement_pct": <float>
          }
        }
      }
    }

- All 7 benchmarks must appear in both `benchmarks` and `universal.results`
- Per-benchmark average `improvement_pct` must be at least 2.0
- Universal average `improvement_pct` must be at least 0.5
- Universal `improvement_pct` must be >= 0.0 for every benchmark (no regressions)
- Maximum 25 passes per sequence in both sections
- `improvement_pct` = `(oz_count - optimized_count) / oz_count * 100`