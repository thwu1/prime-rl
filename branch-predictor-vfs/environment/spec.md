# VFS Scoring Model — Branch Predictor Design Evaluation

## Simulation Data Format

Each `.out` file in `/app/data/<predictor>/` contains a single CSV line with 12 fields:

| Index | Field                           | Type       |
|-------|---------------------------------|------------|
| 0     | trace_name                      | string     |
| 1     | instructions                    | int        |
| 2     | branches                        | int        |
| 3     | conditional_branches            | int        |
| 4     | prediction_blocks (N_pred)      | int        |
| 5     | extra_cycles                    | int        |
| 6     | p1_p2_divergences (D)           | int        |
| 7     | divergences_at_block_end (D_end)| int        |
| 8     | p2_mispredictions (M)           | int        |
| 9     | p1_latency                      | float      |
| 10    | p2_latency                      | float      |
| 11    | energy_per_instruction (EPI)    | int (fJ)   |

## Metric Computation

### Prediction Latencies

P1 and P2 model the hardware pipeline stages of the predictor design. Since these
are physical properties of the hardware implementation, latency is determined
globally across all traces:

    P1 = max_t ceil(p1_latency_t)
    P2 = max_t ceil(p2_latency_t)

These values are fixed for a given predictor and used in ALL per-trace
computations — including when aggregating within individual workload categories.

### Per-Trace Derived Metrics

The cycle count depends on the relative ordering of P1 and P2:

    If P2 <= P1:
        cycles = N_pred * max(1, P2)
    Else:
        cycles = N_pred * max(1, P1) + D * P2 - D_end * max(1, P1)

    In both cases: cycles += extra_cycles

Derived metrics:

    IPC = instructions / cycles
    MPI = M / instructions
    CPI = MPI * (P2_exec + P2 - max(1, min(P1, P2)))

where P2_exec = 9 (pipeline stages from P2 prediction to execution).

EPI is read directly from field 11.

### Aggregation

Given T traces (or T traces within a category for category-specific analysis):

    IPC_agg = T / sum(1 / IPC_t)       (harmonic mean)
    CPI_agg = (1/T) * sum(CPI_t)       (arithmetic mean)
    EPI_agg = (1/T) * sum(EPI_t)       (arithmetic mean)

## VFS Formula

Reference parameters: IPC_0 = 8, CPI_0 = 0.0315, EPI_0 = 1000 fJ

Technology parameters:

    alpha = 1.625
    beta  = 4 * alpha / (alpha - 1)^2
    gamma = 2 / (alpha - 1)
    r     = 0.05          (branch predictor energy fraction)

Derived quantities:

    WPI_0 = IPC_0 * CPI_0
    WPI   = IPC * CPI

Throughput speedup relative to reference:

    S = (IPC / IPC_0) * (1 + WPI_0) / (1 + WPI)

Normalized energy per instruction:

    lambda = 1 / (1 + WPI_0 / 2) - r
    E_hat  = [(EPI / EPI_0) * r + lambda * S^gamma] * (1 + WPI / 2)

VFS score:

    VFS = S * alpha * [1 - 2 / (1 + sqrt(1 + beta / (S * E_hat)))]

## Deployment-Weighted Analysis

Trace metadata in `/app/traces.json` assigns each trace to a workload category
with deployment weight w_c.

For each predictor, using global P1/P2 latencies:

1. Compute per-trace IPC, CPI, EPI for all traces.
2. Aggregate within each category c to obtain (IPC_c, CPI_c, EPI_c).
3. Combine across categories:

        IPC_w = 1 / sum(w_c / IPC_c)
        CPI_w = sum(w_c * CPI_c)
        EPI_w = sum(w_c * EPI_c)

4. VFS_weighted = VFS(IPC_w, CPI_w, EPI_w)

## Per-Category VFS Analysis

For each predictor and each workload category independently:

1. Use the global P1/P2 latencies (these are hardware properties — identical
   regardless of which subset of traces is being analyzed).
2. Aggregate per-trace metrics within the single category to obtain
   (IPC_c, CPI_c, EPI_c).
3. Compute VFS_c = VFS(IPC_c, CPI_c, EPI_c).

This reveals which predictor designs are specialists (strong in specific workload
types) versus generalists (uniformly strong across categories).

## Required Output

Write `/app/results.json` with the following structure:

```json
{
  "vfs_scores": {"<predictor>": <float 6dp>, ...},
  "ranking": ["<best>", "<second>", ...],
  "best_predictor": "<name>",
  "best_vfs": <float 6dp>,
  "pareto_optimal": ["<name>", ...],
  "dominated": ["<name>", ...],
  "elasticity_at_best": {"ipc": <float 6dp>, "cpi": <float 6dp>, "epi": <float 6dp>},
  "optimal_improvement": "<ipc|cpi|epi>",
  "weighted_vfs_scores": {"<predictor>": <float 6dp>, ...},
  "weighted_ranking": ["<best>", ...],
  "per_category_vfs": {"<predictor>": {"<category>": <float 6dp>, ...}, ...},
  "category_specialists": {"<category>": "<predictor>", ...},
  "rank_stability": {"<predictor>": {"standard_rank": <int>, "weighted_rank": <int>, "shift": <int>, "classification": "<str>"}, ...},
  "most_efficient": "<predictor>"
}
```

### Field Definitions

- **vfs_scores**: Standard VFS score for each predictor (6 decimal places).
- **ranking**: Predictors sorted by standard VFS, descending.
- **best_predictor**: Top-scoring predictor under standard VFS.
- **best_vfs**: Its VFS score (6dp).
- **pareto_optimal**: Predictors not dominated in (IPC up, CPI down, EPI down)
  metric space. Predictor P dominates Q iff IPC_P >= IPC_Q AND CPI_P <= CPI_Q
  AND EPI_P <= EPI_Q with at least one strict inequality. Alphabetical order.
- **dominated**: Predictors that ARE dominated. Alphabetical order.
- **elasticity_at_best**: VFS elasticity e_x = (dVFS/dx)(x/VFS) at the best
  predictor's operating point. Compute numerically using central finite
  differences with delta = 0.001 relative perturbation. 6dp.
- **optimal_improvement**: Parameter with largest |elasticity|.
- **weighted_vfs_scores**: Deployment-weighted VFS for each predictor (6dp).
- **weighted_ranking**: Sorted by weighted VFS, descending.
- **per_category_vfs**: For each predictor and each workload category, the VFS
  score computed using only traces within that category (6dp). Global P1/P2
  latencies must be used.
- **category_specialists**: For each workload category, the predictor with the
  highest category-specific VFS score.
- **rank_stability**: For each predictor: 1-indexed positions in standard and
  weighted rankings, the absolute rank shift, and a classification:
  "stable" (shift 0-1), "workload-sensitive" (shift 2-3),
  "highly-sensitive" (shift >= 4).
- **most_efficient**: Predictor with the highest (standard VFS / EPI_cbp) ratio,
  representing the best scoring performance per unit of energy consumed.
