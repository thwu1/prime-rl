A distributed DNN training cluster configuration is provided at `/app/config.json` containing three scenarios with different failure models and cluster sizes. The config includes a `task_dna` string that must be incorporated into your output for verification. Implement `/app/checkpoint_optimizer.py` that reads the configuration, performs checkpoint cost-benefit analysis for each scenario, and writes results to `/app/results.json`.

Each scenario specifies a multi-worker data-parallel training cluster where any single worker failure halts training and requires rollback to the last checkpoint. Worker failures are i.i.d. After each checkpoint or failure recovery, the system-level failure process restarts from age zero (fresh draw).

For each scenario, compute:

**System MTBF**: For N workers with i.i.d. Weibull(k, λ_worker) failure times, the system time-to-first-failure follows Weibull(k, λ_sys) where λ_sys = λ_worker · N^(−1/k) and λ_worker = MTBF_worker / Γ(1 + 1/k). For exponential failures (k=1), this reduces to MTBF_sys = MTBF_worker / N.

**Optimal checkpoint interval**: Find δ (seconds) minimizing expected total wall-clock time using renewal theory. The expected time to successfully complete one protected interval of duration τ (with age-reset failures) is: E_complete(τ) = (1/S(τ) − 1) · (E[X | X < τ] + R) + τ, where S(τ) is the Weibull survival function and E[X | X < τ] is the truncated mean. The total expected time for periodic checkpointing is composed of ⌊W/δ⌋ full intervals (each δ useful work + C checkpoint cost) plus a final partial interval of remaining work with no checkpoint cost. After finding continuous δ*, align to the nearest whole number of iterations: δ_iter = max(1, round(δ*/iter_time)), δ_aligned = δ_iter × iter_time.

**Expected total time** for four strategies: (1) no checkpointing, (2) periodic at the optimal interval, (3) periodic at the fixed interval from config, (4) zero-cost per-iteration checkpointing (δ = iteration_time, C = 0), modeling gradient-replication-based approaches like Checkmate.

**Overhead ratio**: `(expected_time − base_time) / base_time` where `base_time = total_iterations × iteration_time_sec`.

**Monte Carlo validation**: Simulate each strategy (in order: no_checkpoint, optimal, fixed, zero_cost) using the specified random seed with `numpy.random.default_rng(seed)` and number of runs. A single RNG instance is created per scenario and shared sequentially across all four strategies in the order listed. Report mean, standard deviation, and 95% confidence interval (mean ± 1.96·σ/√n).

**Verification digest**: Compute a SHA-256 hex digest of the string formed by concatenating `task_dna` with a pipe-separated list of each scenario's `system_mtbf_sec` (rounded to 2 decimal places) and `optimal_checkpoint_interval_iter`, in scenario order as listed in config. Format: `{task_dna}|{mtbf1:.2f}|{opt_iter1}|{mtbf2:.2f}|{opt_iter2}|...`

Output `/app/results.json` with this structure:

```json
{
  "task_dna": "<echoed from config>",
  "verification_digest": "<sha256 hex of formatted string>",
  "scenarios": {
    "<scenario_name>": {
      "system_mtbf_sec": <float>,
      "optimal_checkpoint_interval_sec": <float>,
      "optimal_checkpoint_interval_iter": <int>,
      "expected_time": {
        "no_checkpoint_sec": <float>,
        "optimal_periodic_sec": <float>,
        "fixed_periodic_sec": <float>,
        "zero_cost_per_iter_sec": <float>
      },
      "overhead_ratio": {
        "no_checkpoint": <float>,
        "optimal_periodic": <float>,
        "fixed_periodic": <float>,
        "zero_cost_per_iter": <float>
      },
      "monte_carlo": {
        "no_checkpoint": {"mean": <float>, "std": <float>, "ci_lower": <float>, "ci_upper": <float>},
        "optimal_periodic": { ... },
        "fixed_periodic": { ... },
        "zero_cost_per_iter": { ... }
      }
    }
  }
}
```