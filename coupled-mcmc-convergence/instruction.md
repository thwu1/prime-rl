A Python library at `/app/couplings/` provides infrastructure for coupled Markov chain Monte Carlo experiments, but several core functions are incomplete (they raise `NotImplementedError`). A mathematical specification is in `/app/spec.md`. Supporting code — data structures, a reference single-sample implementation, and the Metropolis acceptance helper — is already in place.

Produce the following:

1. **Working library** — all functions in `/app/couplings/` that currently raise `NotImplementedError` must be fully implemented and correct.

2. **Benchmark database** — run `/app/benchmark.py` (after the library is functional) to populate `/app/results.db`, a SQLite database containing convergence metrics for multiple sampler configurations and target distributions.

3. **Analysis queries** — create `/app/analysis.sql` containing exactly three SQL queries, each preceded by a `-- QUERY N` comment line (N = 1, 2, 3):
   - Query 1: For each target distribution, identify the configuration with the lowest mean meeting time. Output columns: `target`, `best_config`, `mean_meeting_time`.
   - Query 2: Rank all configurations by median meeting time for the `correlated_8d` target. Output columns: `config`, `median_meeting_time`, `rank`.
   - Query 3: For each target, compute the acceptance-rate spread (max mean x-acceptance rate minus min mean x-acceptance rate across configurations). Output columns: `target`, `accept_spread`.

4. **Custom proposal matrix** — save an 8×8 NumPy covariance matrix to `/app/optimal_proposal.npy` that, when used as the proposal covariance for the `correlated_8d` target in `/app/evaluate_proposal.py`, achieves a mean meeting time ≤ 50. The benchmark's built-in configurations all use isotropic proposals; your matrix must outperform the best of them.