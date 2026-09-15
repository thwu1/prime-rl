Build `/app/evaluator/` — a Python package that implements a generalization-aware GPU kernel evaluation pipeline inspired by the AgentKernelArena methodology.

The system tests whether optimized GPU kernels generalize to unseen input configurations. It does this by: (1) injecting held-out test shapes into kernel source files via text-based codegen replacement, (2) computing gated performance scores, and (3) classifying generalization outcomes across tasks using conditional correctness analysis.

## Input data

Pre-loaded at `/app/data/`:
- `task_manifest.yaml` — task registry with paths to all data files
- `workspaces/task_XX/` — kernel source files (Python) for 5 tasks
- `held_out_configs/task_XX.yaml` — injection specifications per task
- `eval_results/task_XX_{orig,opt}.yaml` — pre-computed evaluation results on held-out shapes
- `original_run_results/task_XX.yaml` — original (non-held-out) evaluation results

## Required output

Run the pipeline to produce `/app/output/heldout_summary.yaml` with aggregate generalization metrics.

## Required API (tested by import)

**`/app/evaluator/injection.py`**:
- `replace_test_shapes(source: str, replacement_code: str) -> str` — Replace a `TEST_SHAPES = [...]` assignment using bracket balancing to find the extent of the list literal. Must not match similarly-named variables (e.g. `TEST_SHAPES_EXTENDED`). Must preserve surrounding code.
- `replace_function(source: str, func_name: str, replacement_code: str) -> str` — Replace a top-level function definition using indentation analysis. The function body includes all lines indented deeper than the `def` line, plus blank/comment lines between body lines. Must handle blank lines within function bodies.
- `raw_replace(source: str, old_code: str, new_code: str) -> str` — Exact substring replacement. Raise `ValueError` if `old_code` is not found in `source`.
- `apply_injection(source: str, injection_spec: dict) -> str` — Dispatch to the appropriate strategy based on `injection_spec["find_marker"]`: value `"TEST_SHAPES"` uses `replace_test_shapes`; value starting with `"def "` uses `replace_function` (extract func name); value `"raw_replace"` uses `raw_replace` with `injection_spec["old_code"]`.

**`/app/evaluator/scoring.py`**:
- `resolve_speedup_ratio(speedup_ratio, base_time, opt_time) -> float` — Return the explicit `speedup_ratio` if it is a positive number; else compute `base_time / opt_time` if both are positive; else return `0.0`.
- `score(pass_compilation: bool, pass_correctness: bool, base_time: float, opt_time: float, speedup_ratio: float = 0.0) -> float` — Gated scoring: return `0.0` if compilation failed; add `20.0` for compilation; add `100.0` for correctness; add `resolve_speedup_ratio() * 100.0` for performance.

**`/app/evaluator/analysis.py`**:
- `classify_generalization(orig_correct: bool, opt_correct: bool) -> str` — Return `"both_pass"` if both correct, `"opt_regression"` if only orig correct, `"both_fail"` if neither correct, `"opt_improvement"` if only opt correct.
- `compute_summary(task_results: list) -> dict` — Each element is a dict with keys: `task_name`, `generalization_status`, `orig_heldout_pass_correctness`, `opt_pass_correctness`, `heldout_speedup`, `original_run_speedup`, `heldout_score`, `original_run_score`. Compute: `total_tasks`, `quadrant_counts` (dict mapping status to count), `conditional_correctness` (with `orig_correct_count`, `opt_also_correct_count`, `rate_pct` = percentage rounded to 1 decimal), `heldout_speedup_stats` (mean/median of `heldout_speedup` for `both_pass` tasks with positive speedup), `original_run_speedup_stats` (same for `original_run_speedup`), `generalization_gap` (with `correctness_retention_pct` and `speedup_mean_delta`), and `per_task` list.

**`/app/evaluator/pipeline.py`**:
- `run_pipeline(data_dir: str, output_dir: str) -> dict` — Read `task_manifest.yaml`, process each task (apply injections to workspace copies written to `output_dir/injected/`, read eval results, classify, score), compute summary via `compute_summary`, write `heldout_summary.yaml` to `output_dir`. Return the summary dict.