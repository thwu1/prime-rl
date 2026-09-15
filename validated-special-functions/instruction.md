A specification file at `/app/eval_spec.json` lists 20 special function evaluation requests. Each entry specifies a function name, its parameters, and a required number of correct decimal digits (at least 40).

Build a validated evaluation system that computes each requested value and writes results to `/app/results.json`. The output must be a JSON array where each entry has:

- `"id"`: matching the spec entry id
- `"value_re"`: real part of the computed value as a decimal string
- `"value_im"`: imaginary part (or `"0"` for real results)
- `"error_bound"`: a positive float upper-bounding the absolute error of the reported value
- `"methods"`: list of at least 2 independent computational method names used for cross-validation

Requirements:

1. Every result must be accurate to at least 40 decimal digits (i.e., absolute error < 5e-41 relative to the leading digit scale, or `|computed - exact| / max(|exact|, 1e-300) < 1e-40`).

2. Each result must be cross-validated using at least two mathematically independent algorithms (e.g., power series vs. continued fraction vs. asymptotic expansion vs. integral representation). Simply evaluating the same formula twice does not count.

3. The reported `error_bound` must be a valid upper bound on the actual error (it must be >= the true error and <= 1e-40).

4. The evaluation points include numerically challenging regimes: arguments near zeros of Bessel functions, the Gamma function near negative integers, Airy functions in the oscillatory-to-exponential transition region, and hypergeometric functions with large parameters where naive summation suffers catastrophic cancellation.

Functions covered: `gamma`, `digamma`, `besselj`, `bessely`, `airy_ai`, `airy_bi`, `hyp1f1`, `hyp2f1`, `expint_e1`.

The system must handle both real and complex arguments as specified in the evaluation requests.