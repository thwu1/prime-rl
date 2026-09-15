`/app/problem.json` defines a five-part computational challenge. Each part specifies input parameters and describes what must be computed. Produce `/app/results.json` containing correct numerical results for all five parts, conforming exactly to the schema below.

The underlying mathematics is non-trivial. Numerical tolerance: relative 1e-6 for all computed values.

## Output: `/app/results.json`

```json
{
  "part1": {
    "two_sided_normal": { "rho": <float>, "log_superMG_values": [<float>, ...] },
    "one_sided_normal": { "rho": <float>, "log_superMG_values": [<float>, ...] },
    "gamma_exponential": { "rho": <float>, "leading_constant": <float>, "log_superMG_values": [<float>, ...] }
  },
  "part2": {
    "two_sided_normal_bounds": [<float>, ...],
    "gamma_exponential_bounds": [<float>, ...],
    "tighter_family": [<string>, ...],
    "crossover_detected": <bool>
  },
  "part3": {
    "e_values_at_checkpoints": [<float>, ...],
    "reject_at_checkpoints": [<bool>, ...],
    "first_rejection_time": <int or null>
  },
  "part4": {
    "arithmetic_mean": [<float>, ...],
    "geometric_mean": [<float>, ...],
    "f_combination": [<float>, ...],
    "calibrated_p_values": [<float>, ...]
  },
  "part5": {
    "lower_bounds": [<float>, ...],
    "upper_bounds": [<float>, ...],
    "widths": [<float>, ...]
  }
}
```

## Validation criteria

- Array lengths match the corresponding evaluation points, `v_values`, checkpoints, or sets in `problem.json`.
- E-values (Part 3) are positive. When the true mean differs from the null value, e-values at later checkpoints exceed those at earlier ones.
- Mixture bounds (Part 2) are positive and strictly increasing with intrinsic time.
- Each `tighter_family` entry is `"two_sided_normal"` or `"gamma_exponential"`, indicating which family yields the smaller bound at that intrinsic time. `crossover_detected` is `true` if the tighter family changes across the intrinsic times, `false` otherwise.
- Calibrated p-values (Part 4) lie in [0, 1].
- Confidence interval widths (Part 5) are positive and decrease as sample size grows.
- Each width equals the difference between the corresponding upper and lower bounds.