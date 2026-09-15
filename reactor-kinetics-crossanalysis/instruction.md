Build `/app/reactor_analysis.py`. Running `python3 /app/reactor_analysis.py` must read all run parameters from `/app/config.json` and write computed results to `/app/results.json`.

The config specifies a Cantera mechanism name, gas mixture composition, system pressure, initial temperatures for ignition simulations, a reference temperature for sensitivity analysis, CSTR inlet temperature, and a residence-time multiplier for PSR sensitivity evaluation. The script must load the specified mechanism at runtime, discover its structure, and use the config parameters throughout.

**Output schema** (`/app/results.json`):

```json
{
  "mechanism_n_species": <int>,
  "mechanism_n_reactions": <int>,
  "ignition_delays": {"<T_K>": <float_s>, ...},
  "cv_peak_temperatures": {"<T_K>": <float_K>, ...},
  "crossover_temperature": <int_K>,
  "cv_sensitivity": [{"index": <int>, "equation": "<str>", "sensitivity": <float>}, ...],
  "tau_ext": <float_s>,
  "s_curve": [[<tau_s>, <T_K>], ...],
  "psr_sensitivity": [{"index": <int>, "equation": "<str>", "sensitivity": <float>}, ...],
  "spearman_rho": <float>,
  "top5_cv": ["<equation>", ...],
  "top5_psr": ["<equation>", ...]
}
```

`mechanism_n_species`, `mechanism_n_reactions`: counts discovered from the loaded mechanism.

`ignition_delays`: adiabatic constant-volume ignition delay (s) at each config temperature, keyed by temperature string. One entry per config temperature.

`cv_peak_temperatures`: peak temperature (K) reached during each constant-volume explosion.

`crossover_temperature` (int, K): the highest config temperature at which the ignition delay is anomalously long relative to the Arrhenius trend established by the higher temperatures in the set.

`cv_sensitivity`: normalized sensitivity of ignition delay to each reaction's rate constant at the config's reference temperature. Sorted descending by absolute value. Each entry: `index` (reaction index), `equation` (reaction string), `sensitivity` (float).

`tau_ext`: PSR extinction residence time — the smallest residence time sustaining combustion on the burning branch.

`s_curve`: at least 100 `[tau, T_exit]` pairs tracing the burning branch through the extinction transition, sorted descending by tau. Must capture both hot steady-state temperatures and the extinction drop.

`psr_sensitivity`: normalized sensitivity of PSR exit temperature to each reaction rate, evaluated at tau = multiplier x tau_ext on the burning branch. Same entry format and sorting as `cv_sensitivity`.

`spearman_rho`: Spearman rank correlation coefficient between absolute CV and PSR sensitivity magnitudes across all reactions.

`top5_cv`, `top5_psr`: top 5 reaction equation strings by absolute sensitivity for each reactor type.
