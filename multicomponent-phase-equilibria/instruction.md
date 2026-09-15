Create `/app/phase_solver.py` that reads `/app/systems.json`, performs multi-component phase equilibrium calculations using the Peng-Robinson cubic equation of state, and writes results to `/app/results.json`.

`/app/systems.json` contains `{"systems": [...]}` where each system specifies:

- `id`: string identifier
- `eos`: `"PR"` (Peng-Robinson)
- `components`: object with arrays `CASs`, `Tcs` (K), `Pcs` (Pa), `omegas`, `MWs` (g/mol), and `Cp_poly_fits` — a list of `{"T_min", "T_max", "coefficients": [c0..c8]}` defining ideal-gas Cp = c0·T^8 + c1·T^7 + ... + c8 (J/(mol·K))
- `kijs`: symmetric binary interaction parameter matrix (NxN)
- `calculations`: list of calculation requests

Calculation types:

**`flash_PT`**: Fields `T` (K), `P` (Pa), `zs` (feed mole fractions), `allow_VLL` (bool). Perform isothermal-isobaric flash. When `allow_VLL` is true, test for liquid-liquid phase splitting (up to three coexisting phases). Report `phase_count` (int), `betas` (molar phase fractions, gas first if present, then liquids), `compositions` (list of mole-fraction vectors, same order as `betas`).

**`bubble_pressure`**: Fields `T` (K), `zs`. Compute bubble-point pressure. Report `pressure` (Pa).

**`dew_pressure`**: Fields `T` (K), `zs`. Compute dew-point pressure. Report `pressure` (Pa).

Normalize `zs` to sum to 1.0 before calculations.

Output schema for `/app/results.json`:
```json
{
  "<system_id>": {
    "calculations": [
      {
        "type": "flash_PT",
        "phase_count": 3,
        "betas": [0.35, 0.32, 0.33],
        "compositions": [[...], [...], [...]]
      },
      {
        "type": "bubble_pressure",
        "pressure": 101325.0
      }
    ]
  }
}
```

Calculation results must appear in the same order as the input requests. All floating-point values must be accurate to relative tolerance 5e-3 for values above 1e-10, and absolute tolerance 1e-8 for near-zero values.

The input includes four systems: a binary VLE (ethane/pentane), a ternary hydrocarbon phase envelope (pentane/hexane/heptane), a ternary VLL system (water/methane/octane with three flash conditions including a high-pressure case), and a 9-component natural gas mixture.
