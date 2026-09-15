An evaluation campaign tested LLM-generated GPU kernels across 15 operator-level problems on an A100 GPU. The results and metadata are stored under `/app/` in multiple formats accumulated during the project's evolution. An incomplete analysis script exists at `/app/pipeline.py` but produces incorrect results.

Produce a correct `/app/report.json` by reconciling all available data sources under `/app/`, handling any data quality issues you discover, applying documented corrections, and computing the benchmark metrics below.

The report must contain these top-level keys:

- **`fast_p`**: Dict mapping speedup threshold strings (`"0.0"`, `"0.5"`, `"1.0"`, `"1.5"`, `"2.0"`) to the fraction of all 15 problems where the greedy sample (`sample_id=0`) is both correct and achieves at least that speedup ratio over the PyTorch baseline.

- **`pass_at_k`**: Dict mapping k strings (`"1"`, `"3"`, `"5"`) to the average unbiased pass@k across all problems, using the combinatorial estimator from Chen et al. (2021). Exclude problems where k exceeds sample count.

- **`geometric_mean_speedup`**: Geometric mean of greedy-sample speedup ratios, computed only over problems with a correct greedy sample and valid timing.

- **`anomalies`**: Sorted list of `problem_id` integers where any correct sample achieves a speedup exceeding the roofline-model theoretical maximum. The roofline bounds minimum execution time from peak FP32 throughput and peak memory bandwidth.

- **`corrected_fast_p`**: Same as `fast_p` but computed only over non-anomalous problems.

- **`difficulty_breakdown`**: Dict with keys `"compute_bound"` and `"memory_bound"`, each containing `fast_p` at threshold 1.0 for problems of that roofline-classified bottleneck type.

- **`flaky_problems`**: Sorted list of `problem_id` integers where correctness varies across samples (some correct, some not).

- **`per_problem`**: List of 15 dicts, each with: `problem_id` (int), `name` (str), `num_compiled` (int), `num_correct` (int), `num_samples` (int), `greedy_speedup` (float or null), `best_speedup` (float or null), `is_anomalous` (bool), `roofline_time_us` (float), `max_theoretical_speedup` (float), `bottleneck` (str: `"compute_bound"` or `"memory_bound"`).