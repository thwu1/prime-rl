The project at `/app/` contains R files implementing two actuarial reserving methods: the Mack Chain Ladder and the Munich Chain Ladder. Both implementations have errors, and the Munich Chain Ladder is incomplete.

Running `Rscript /app/run_pipeline.R` must succeed and produce `/app/results.json` with this schema:

```json
{
  "raa_total_mack_se": <number>,
  "genins_skewness": [<10 numbers>],
  "genins_overall_skewness": <number>,
  "mcl_paid_ultimate": <number>,
  "mcl_incurred_ultimate": <number>
}
```

**Golden values and tolerances:**

| Field | Expected | Tolerance |
|---|---|---|
| `raa_total_mack_se` | 26880.74 | ±0.01 |
| `genins_skewness` | [0, 0, -0.029, -0.043, -0.001, 0.180, 0.055, 0.267, 0.286, 0.314] | ±0.002 per element |
| `genins_overall_skewness` | 0.214 | ±0.002 |
| `mcl_paid_ultimate` | 34055.98 | ±1.0 |
| `mcl_incurred_ultimate` | 33291.31 | ±1.0 |

**Source files:**

- `/app/reserving.R` — Mack Chain Ladder (Mack 1993/1999) with recursive standard error computation, sigma estimation, and Cornish-Fisher skewness quantiles. Contains mathematical errors in the recursive formulas.
- `/app/munich.R` — Munich Chain Ladder (Quarg & Mack 2004). Extends the standard chain ladder by exploiting the correlation between paid and incurred claim development via standardized residual regression. The residual computation is unimplemented, and existing model fitting and recursive correction code contains errors.
- `/app/run_pipeline.R` — Orchestration script. Do not modify the function signatures, parameters, or output logic.

**Constraints:**

- No external R packages. All computation must use base R only.
- The `genins_skewness` array must have exactly 10 elements in origin-period order.
- The Munich Chain Ladder must use the weighted Last-3 LDF selection and tail parameters specified in the pipeline script.
- Output must be valid JSON parseable by Python's `json.load`.
