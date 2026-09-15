An LLVM IR module at `/app/module.ll` and a configuration at `/app/config.json` specify two LLVM optimization pass pipelines — baseline and candidate — along with a target triple. The candidate pipeline introduces instruction count regressions in some functions.

Produce `/app/report.json` that fully characterizes the impact of both pipelines on every function at the LLVM IR and x86-64 assembly levels, and attributes each regression to the earliest responsible pass in the candidate pipeline.

## Report schema

    {
      "per_function": {
        "@func_name": {
          "baseline_ir_count": <int>,
          "candidate_ir_count": <int>,
          "ir_delta": <int>,
          "status": "<improved|regressed|unchanged>",
          "baseline_asm_count": <int>,
          "candidate_asm_count": <int>,
          "asm_delta": <int>
        }
      },
      "bisection": {
        "@func_name": {
          "regressing_pass_index": <int>,
          "regressing_pass_name": "<str>"
        }
      },
      "summary": {
        "total_functions": <int>,
        "num_regressed": <int>,
        "num_improved": <int>,
        "num_unchanged": <int>,
        "total_ir_delta": <int>,
        "total_asm_delta": <int>,
        "unique_regressing_passes": ["<str>"]
      }
    }

## Constraints

- `bisection` entries exist only for functions with `status == "regressed"`
- `regressing_pass_index`: 0-based position within the candidate pipeline's pass sequence
- All deltas: candidate count minus baseline count
- `status`: determined by the sign of `ir_delta`
- `unique_regressing_passes`: sorted, deduplicated
- The LLVM-18 toolchain is available in the environment