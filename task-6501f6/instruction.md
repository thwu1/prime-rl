A specialty chemical company produces four chemicals (C1–C4) from a single bulk feedstock. Feedstock procurement must be committed before uncertain processing conditions and demand materialize. The full problem specification is at `/app/data/problem.json`.

## Problem Structure

**Stage 1 (here-and-now):** Purchase feedstock quantity *x* ≥ 0 at the unit cost specified in the data, before any uncertainty is revealed.

**Stage 2 (wait-and-see):** After uncertain parameters *z* = (*z*₁, *z*₂, *z*₃, *z*₄, *z*₅) are realized, choose production quantities *y*₁, *y*₂, *y*₃, *y*₄ ≥ 0.

**Net unit revenue** for product *i*: *R*ᵢ(*z*) = base\_revenue\_*i* − reactor\_processing\_cost\_*i* · (1 + *z*₁) − separator\_processing\_cost\_*i* · (1 + *z*₂).

**Resource consumption** scales with uncertainty: actual consumption = nominal\_consumption × (1 + *z*ₖ) where the reactor uses *z*₁, separator uses *z*₂, lab uses *z*₃.

**Contract demands:** *y*₁ ≥ min\_demand\_C1 · (1 + *z*₄), *y*₂ ≥ min\_demand\_C2 · (1 + *z*₅).

**Feedstock linkage:** ∑ feedstock\_usage\_*i* · *y*ᵢ ≤ *x*.

**Uncertainty set *Z*:** Each |*z*ₖ| ≤ δₖ (box bounds from data), with budget constraint ∑ₖ |*z*ₖ|/δₖ ≤ Γ (from data).

## Required Solutions

Compute optimal first-stage decisions for two formulations and write results to `/app/results.json`:

**Robust (worst-case):** Find *x* that maximizes worst-case total profit: max_{*x*≥0} { −feedstock\_cost · *x* + min_{*z*∈*Z*} *Q*(*x*, *z*) }, where *Q*(*x*, *z*) is the optimal second-stage profit. Use the stopping tolerance and iteration limit from the problem data.

**Stochastic (expected-value):** Find *x* that maximizes expected total profit over randomly sampled scenarios from *Z*, using the seed and sample count from the data.

```json
{
  "robust_optimal_objective": <float>,
  "robust_first_stage_x": <float>,
  "robust_iterations": <int>,
  "stochastic_optimal_objective": <float>,
  "stochastic_first_stage_x": <float>
}
```

Use Pyomo with the `appsi_highs` solver interface (HiGHS).