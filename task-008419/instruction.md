A specification file at `/app/code_spec.json` defines a bivariate bicycle (BB) quantum error-correcting code from the family introduced by Bravyi, Cross, Gambetta, Maslov, Rall, and Yoder. The code is specified by polynomial generators `a(x,y)` and `b(x,y)` over the group algebra `F_2[Z_l × Z_m]`, along with noise simulation parameters (physical error rates, number of Monte Carlo shots, random seed, and decoder configuration).

Analyze this code and produce `/app/results.json` containing:

- **Code parameters**: the number of physical qubits `n`, logical qubits `k`, GF(2) ranks of the X- and Z-type parity check matrices (`hx_rank`, `hz_rank`), whether the CSS orthogonality condition holds (`css_valid`), and the uniform stabilizer generator weight (`stabilizer_weight`).

- **Logical error rates**: for each physical error rate `p` listed in the spec, the estimated logical error rate under code-capacity depolarizing noise with `num_shots` Monte Carlo samples using the specified `seed` for reproducibility. Under depolarizing noise at rate `p`, each qubit independently suffers an X, Y, or Z error with probability `p/3`. Use the decoder settings provided in the spec.

```json
{
  "code_parameters": {
    "n": <int>,
    "k": <int>,
    "hx_rank": <int>,
    "hz_rank": <int>,
    "css_valid": <bool>,
    "stabilizer_weight": <int>
  },
  "logical_error_rates": {
    "<p as string>": <float>,
    ...
  }
}
```