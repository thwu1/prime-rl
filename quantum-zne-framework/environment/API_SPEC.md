# Error Mitigation System — API Specification

## Module: `noise_scaling.py`

Noise amplification through circuit manipulation. The simulator exposes
gate definitions and adjoint mappings — study them to understand how
circuits can be restructured to amplify noise without altering the
ideal (noiseless) computation.

### `fold_circuit_global(circuit: dict, scale_factor: int) -> dict`

Amplify the effective noise of a quantum circuit by an integer factor.

- **Input**: a circuit dict (as returned by `load_circuit`) and an odd integer `scale_factor >= 1`
- **Output**: a new circuit dict with the same `n_qubits`, `id`, and `observable`
- **Gate count constraint**: output must contain exactly `scale_factor * len(original_gates)` gates
- **Correctness**: the folded circuit must produce identical expectation values when `noise_level=0.0`
- **Noise behavior**: under nonzero noise, the effective error scales with `scale_factor`
- **Validation**: raise `ValueError` for even integers, non-integers, or values < 1

### `fold_gates_from_end(circuit: dict, scale_factor: float) -> dict`

Amplify noise by folding individual gates, starting from the end of the circuit.

- **Input**: a circuit dict and a float `scale_factor >= 1.0`
- **Output**: a new circuit dict preserving metadata
- **Number of gates folded**: `ceil(n * (scale_factor - 1) / 2)` where `n = len(original_gates)`
- **Gate count constraint**: `n + 2 * num_folded` total gates
- **Correctness**: must preserve noiseless equivalence

---

## Module: `extrapolation.py`

Methods for inferring the zero-noise limit from measurements taken at
multiple noise amplification levels.

### `richardson_extrapolate(scale_factors: list, values: list) -> float`

Compute the zero-noise limit using Richardson extrapolation.

- **Input**: lists of noise scale factors and corresponding measured values
- **Output**: extrapolated value at `scale_factor = 0`

### `poly_extrapolate(scale_factors: list, values: list, order: int) -> float`

Polynomial extrapolation to zero noise.

- **Input**: scale factors, values, and the polynomial degree
- **Output**: fitted polynomial evaluated at `scale_factor = 0`

### `exponential_extrapolate(scale_factors: list, values: list, asymptote: float = None) -> float`

Exponential model extrapolation: fit `y = a + b * exp(c * x)` to the data.

- **Input**: scale factors and values; optional fixed asymptote `a`
- **Output**: model value at `x = 0` (i.e., `a + b`)
- If `asymptote` is provided, fix `a` to that value and fit only `b` and `c`

---

## Module: `run_benchmark.py`

Executable benchmark pipeline. When run (`python3 /app/run_benchmark.py`):

1. Process every `.json` circuit in `/app/circuits/`
2. Use `noise_level = 0.01` and `scale_factors = [1, 3, 5]` with global circuit folding
3. Apply all three extrapolation methods
4. Write results to `/app/results/benchmark.json`

### Output schema

JSON object keyed by circuit `id`. Each entry:

```json
{
  "ideal": 0.0,
  "unmitigated": 0.0,
  "scale_factors": [1, 3, 5],
  "noisy_values": [0.0, 0.0, 0.0],
  "richardson": 0.0,
  "polynomial_2": 0.0,
  "exponential": 0.0,
  "best_method": "method_name"
}
```

- `ideal`: expectation value at `noise_level=0.0`
- `unmitigated`: expectation value at `noise_level=0.01` (no mitigation)
- `noisy_values`: expectation values at each amplified noise level
- `polynomial_2`: degree-2 polynomial extrapolation result
- `best_method`: name of the extrapolation method whose result is closest to `ideal` (one of `"richardson"`, `"polynomial_2"`, `"exponential"`)
