# SMT-COMP 2026 Single Query Track Scoring Specification

## 1. Competition Configuration

- **Track**: Single Query (non-incremental benchmarks, one `check-sat` per benchmark)
- **Wall-clock time limit** `T`: Given in `config.time_limit_s` of the input data
- **CPU cores** `m`: Given in `config.cpu_cores` of the input data
- **CPU time limit**: `m * T`

## 2. Input Data

The competition data (`competition_data.json`) contains:
- `config`: time limit and CPU cores
- `divisions`: mapping from division name to list of logics
- `solvers`: mapping from solver name to solver metadata (type, base_solver for derived, competitive flag, entered divisions)
- `benchmarks`: list of benchmark objects with `id`, `division`, `logic`, `status` (sat/unsat/unknown)
- `results`: list of result objects with `benchmark`, `solver`, `result` (sat/unsat/unknown/timeout), `wallclock_time`, `cpu_time`

A solver not supporting a logic in a division it entered is scored as if it returned `unknown` within zero time. If no result entry exists for a solver/benchmark pair where the solver entered the division, treat it as `unknown` with zero time.

## 3. Benchmark Scoring (Parallel)

The **parallel benchmark score** of a solver on a single benchmark is a tuple `(e, n, w, c)`:

- `e` in {0, 1}: error count
- `n` in {0, 1}: correctly solved count
- `w` >= 0: wall-clock time score (seconds)
- `c` >= 0: CPU time score (seconds)

### Single Query Track scoring rules:

- **No response or unknown**: If the solver's result is `unknown` or `timeout`: `e=0, n=0`
- **Correct**: If the result is `sat` or `unsat` AND (matches the benchmark status OR the benchmark status is `unknown`): `e=0, n=1`
- **Incorrect**: If the result is `sat` or `unsat` AND does NOT match a known benchmark status (sat/unsat): `e=1, n=0`

### Time scores:

- `w = wallclock_time` if the benchmark was **correctly solved** (e=0 AND n=1), else `w = 0`
- `c = cpu_time` if the benchmark was **correctly solved** (e=0 AND n=1), else `c = 0`

Note: `w` and `c` are zero whenever the benchmark was not correctly solved, regardless of whether there was an error, timeout, or unknown result.

## 4. Sequential Benchmark Score

The sequential score imposes a **virtual CPU time limit** equal to the wall-clock time limit `T`. A solver result is only considered for the sequential score if its CPU time score `c <= T`.

Given a parallel benchmark score `(e, n, w, c)`, the corresponding sequential score `(eS, nS, cS)` is:
- If `c > T`: `eS=0, nS=0, cS=0`
- Otherwise: `eS=e, nS=n, cS=c`

**Important**: The sequential score uses the CPU time score `c` from the parallel score (not the actual CPU time `ac`). Since for Single Query track `c` equals `cpu_time` only when correctly solved (otherwise `c=0`), this means:
- Unsolved benchmarks always have `c=0 <= T`, so they remain as `(0, 0, 0)` in sequential scoring
- Only correctly-solved benchmarks with `cpu_time > T` get zeroed out

## 5. Division Scoring and Disagreement Removal

### Sound Solver

A solver is **sound** on benchmarks with **known status** for a division if its parallel benchmark score has `e=0` for every benchmark in the division with known status (sat or unsat). Unknown-status benchmarks do not affect soundness.

### Disagreement Removal

Before computing division scores, benchmarks with **unknown** status are removed from the competition results if two or more solvers that are:
1. Sound on benchmarks with known status in the division, AND
2. Competitive

**disagree** on the benchmark (i.e., one reports `sat` and another reports `unsat`).

Only the remaining benchmarks are used for division scoring.

### Parallel Division Score

The parallel division score for a solver in a division with benchmarks B is the component-wise sum:

```
(E, N, W, C) = sum over b in B of (e_b, n_b, w_b, c_b)
```

### Parallel Division Ranking

A parallel score `(e, n, w, c)` is **better than** `(e', n', w', c')` iff:
- `e < e'`, OR
- `e = e'` AND `n > n'`, OR
- `e = e'` AND `n = n'` AND `w < w'`, OR
- `e = e'` AND `n = n'` AND `w = w'` AND `c < c'`

That is: fewer errors > more correct solutions > less wall-clock time > less CPU time.

### Sequential Division Score

The sequential division score is the component-wise sum of sequential benchmark scores:
```
(ES, NS, CS) = sum over b in B of (eS_b, nS_b, cS_b)
```

A sequential score `(e, n, c)` is **better than** `(e', n', c')` iff:
- `e < e'`, OR
- `e = e'` AND `n > n'`, OR
- `e = e'` AND `n = n'` AND `c < c'`

## 6. PAR-2 Score

The PAR-2 score for a solver in a division modifies the parallel division score by penalizing unsolved benchmarks:

For each benchmark b:
- `par2_w_b = wallclock_time` if `e_b = 0` AND benchmark b is solved (n_b=1), else `par2_w_b = 2 * T`
- `par2_c_b = cpu_time` if `e_b = 0` AND benchmark b is solved (n_b=1), else `par2_c_b = 2 * m * T`

The PAR-2 division score is:
```
(PAR2_W, PAR2_C) = (sum of par2_w_b, sum of par2_c_b)
```

Note: For PAR-2, unsolved means ANY case where the benchmark was not correctly solved: errors, timeouts, unknowns. The penalty uses the **actual** wallclock/CPU time for solved benchmarks and `2T`/`2mT` for unsolved.

## 7. Competition-Wide Rankings

### 7.1 Best Overall Ranking

This ranking selects the most universal solver.

Let `(E_D, N_D, W_D, C_D)` be the parallel division score for a solver in division D. Let `NUM_D` be the total number of benchmarks in division D used in the competition (after disagreement removal).

The **normalized correctness score** `nn_D` is:
- `nn_D = (N_D / NUM_D)^2` if `E_D = 0`
- `nn_D = -2` if `E_D > 0`

The **overall score** is:
```
sum over all competitive divisions D the solver entered of: nn_D * log10(NUM_D)
```

Solvers are ranked by overall score (higher is better). Ties are resolved by:
- For parallel scoring: total wall-clock time across all divisions (lower is better)
- For sequential scoring: total CPU time across all divisions (lower is better)

The tiebreaker time is the sum of the `W` (or `CS`) components of the division scores (NOT PAR-2).

### 7.2 Biggest Lead Ranking

For each competitive division D, let `n^D_1` and `n^D_2` be the correctness scores (N component) of the 1st and 2nd ranked solvers (by parallel/sequential ranking).

**Correctness rank** of division D: `(n^D_1 + 1) / (n^D_2 + 1)`

**Wall-clock time rank**: `(w^D_2 + 1) / (w^D_1 + 1)` where `w^D_i` is the W component of the i-th solver's parallel score.

**CPU time rank**: `(c^D_2 + 1) / (c^D_1 + 1)` where `c^D_i` is the C/CS component.

The **biggest lead winner** (parallel) is the winner of the division with the highest correctness rank. Ties are broken by the wall-clock time rank (higher is better).

The **biggest lead winner** (sequential) is determined similarly, with ties broken by the CPU time rank.

### 7.3 Largest Contribution Ranking

This ranking selects the solver that uniquely contributed the most via Virtual Best Solver (VBS) analysis.

**Step 1**: For each division D, identify the set S of **competitive sound solvers** (solvers with E_D = 0 in the division). If |S| <= 2, exclude the division from this ranking.

**Step 2**: Compute the VBS scores for the full set S:

```
vbss_n(D, S) = sum over b in D of max{n^s_b | s in S and n^s_b > 0}
```
(max of empty set is 0)

```
vbss_w(D, S) = sum over b in D of min{w^s_b | s in S and n^s_b > 0}
```
(min of empty set is T, the time limit: 1200)

```
vbss_c(D, S) = sum over b in D of min{c^s_b | s in S and n^s_b > 0}
```
(min of empty set is T for sequential, m*T for parallel)

Wait - correction: the minimum of an empty set is the time limit T (= 1200 seconds) per the rules: "where the minimum of an empty set is 1200 seconds."

**Step 3**: For each solver s in S, compute VBS scores without s: `vbss_n(D, S-{s})`, `vbss_w(D, S-{s})`, `vbss_c(D, S-{s})`.

**Step 4**: Compute contribution ranks for solver s in division D:

```
correctness_rank = 1 - vbss_n(D, S-{s}) / vbss_n(D, S)
wall_rank = 1 - vbss_w(D, S) / vbss_w(D, S-{s})
cpu_rank = 1 - vbss_c(D, S) / vbss_c(D, S-{s})
```

These ranks are in [0, 1]. A rank of 0 means the solver made no impact; 1 means it was the only solver.

**Step 5**: Normalize by multiplying each rank by `nD / N`, where:
- `nD` = number of competitive solver/benchmark pairs in division D (= |competitive solvers in D| * |benchmarks in D|)
- `N` = total number of competitive solver/benchmark pairs across all divisions in the track

**Step 6**: The **largest contribution winner** (parallel) is the solver with the highest normalized correctness rank across all divisions. Ties are broken by the normalized wall-clock rank (parallel) or normalized CPU rank (sequential).

## 8. Derived Solver Eligibility

A derived solver is eligible for winning a division only if it achieves **at least a 10% improvement** on the PAR-2 wallclock score over its base solver in that division:

```
improvement = (base_par2_w - derived_par2_w) / base_par2_w
eligible if improvement >= 0.10
```

A derived solver can win competition-wide rankings (Best Overall, Biggest Lead, Largest Contribution) only if it is eligible in **at least one** division.

## 9. Output

Write all computed scores and rankings to `/app/output.json` following the schema in `/app/output_schema.md`.
