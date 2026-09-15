A training pipeline at `/opt/ga_bench/` fine-tunes a small causal language model using gradient accumulation (GA). The codebase includes four different loss normalization strategies in `/opt/ga_bench/normalizers.py`, each attempting to make GA produce identical results to full-batch training. The pipeline supports variable-length sequences and optional per-token importance weights (simulating curriculum learning or completion-only training via `/opt/ga_bench/dataset.py`).

A SQLite database at `/opt/ga_bench/benchmark_results.db` contains analysis notes on each strategy. A benchmark script at `/opt/ga_bench/run_benchmark.py` tests strategies against full-batch training under four scenarios: uniform-length unweighted, variable-length unweighted, uniform-length weighted, and variable-length weighted.

None of the four existing strategies correctly handle all combinations of variable-length sequences and per-token importance weights during gradient accumulation. Evaluate each strategy's mathematical correctness — determine which scenarios each handles correctly, which it fails, and why. Then design and implement a `UnifiedNormalizer` class in `/opt/ga_bench/normalizers.py` that produces loss and gradients identical to full-batch training for ALL scenarios (unweighted and weighted, uniform and variable-length, across any GA step count). Register it in the `STRATEGIES` dict.

Write an evaluation report to `/opt/ga_bench/evaluation_report.json`:

```json
{
  "strategy_evaluations": [
    {"strategy": "<name>", "correct_scenarios": [...], "incorrect_scenarios": [...], "mathematical_reason": "<why>"}
  ],
  "unified_strategy_description": "<what the unified strategy does>",
  "mathematical_justification": "<proof that GA == full-batch for all cases>"
}
```