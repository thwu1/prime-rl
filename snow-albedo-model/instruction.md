Implement `/app/snow_model.py` — a single-layer snow column model reading SUMMA-format configuration, simulating snowpack under hourly forcing, writing NetCDF output.

**Invocation:** `python3 /app/snow_model.py -m <file_manager_path>`

Run with both `/app/config/fileManager_conDecay.txt` and `/app/config/fileManager_varDecay.txt`. Each selects a different `alb_method` decision (`conDecay` or `varDecay`).

**Configuration** at `/app/config/`: file managers (`keyword 'value'`, `!` = comment), decisions (`name value`), parameters (`name | value | lower | upper`), forcing list (quoted filename). Forcing NetCDF at `/app/data/forcing.nc`: dimensions `(time, hru)`, variables `pptrate` (kg m-2 s-1), `SWRadAtm` (W m-2), `LWRadAtm` (W m-2), `airtemp` (K), `windspd` (m s-1), `airpres` (Pa), `spechum` (kg kg-1). Hourly timestep.

**Output:** `{outFilePrefix}_output.nc` in configured `outputPath`. Dimensions `(time, hru)` with `hru` size 1. Exactly one output row per forcing timestep. `time` coordinate variable required. All eight variables must have shape `(time, 1)` with no NaN values: `scalarSWE` (kg m-2), `scalarSnowDepth` (m), `scalarSnowAlbedo` (dimensionless), `scalarSurfaceTemp` (K), `scalarSenHeatTotal` (W m-2), `scalarLatHeatTotal` (W m-2), `scalarRainPlusMelt` (kg m-2 s-1), `scalarSnowSublimation` (kg m-2 s-1, positive = mass loss). Heat fluxes positive toward surface; no NaN allowed in any flux variable.

**Physical constraints (enforced on both configurations):**
- Albedo in `[albedo_min, albedo_max]` when snow present; resets toward maximum on fresh snowfall
- `conDecay`: inter-event albedo decay rate consistent with configured `tau_const`
- `varDecay`: temperature-dependent decay — faster when warm than when cold
- Surface temperature <= 273.15 K with snow present; always > 200 K
- Melt occurs predominantly near the melting point (majority of melt timesteps above 268 K)
- SWE, depth >= 0; zero SWE implies zero depth; implied density 30-800 kg m-3
- Sublimation rate >= 0; approximate mass conservation across the simulation
- Cold precipitation events increase SWE; peak SWE > 1.0 kg m-2, occurring after early simulation transient
- Sensible heat flux positively correlated with (T_air - T_surface) gradient
- The two configurations produce measurably different SWE, melt, and albedo trajectories

**Comparison report:** Implement `/app/generate_report.py` reading both outputs, writing `/app/comparison_report.json`:
```json
{
  "conDecay": {"peak_swe_kg_m2": <float>, "peak_swe_timestep": <int>, "total_melt_kg_m2": <float>, "mean_snow_albedo": <float>, "snow_covered_hours": <int>, "total_sublimation_kg_m2": <float>},
  "varDecay": {"<same fields>": "..."},
  "divergence": {"max_swe_difference_kg_m2": <float>, "max_albedo_difference": <float>, "melt_onset_difference_hours": <int>}
}
```

Definitions: `snow_covered_hours` = timesteps with SWE > 0.1. `total_melt_kg_m2`, `total_sublimation_kg_m2` = time-integrated (sum * 3600). `mean_snow_albedo` = mean over snow-covered timesteps. `melt_onset_difference_hours` = signed (conDecay - varDecay) first timestep with sustained SWE decrease (> 0.5 kg m-2 drop over next 24h, SWE > 1.0).

**Report validation:** `peak_swe_kg_m2` within 5% of actual max SWE from output; `peak_swe_timestep` within +/-2 of actual argmax. `snow_covered_hours` in [100, 5000]. `total_melt_kg_m2` > 0. `total_sublimation_kg_m2` >= 0. `mean_snow_albedo` within `[albedo_min, albedo_max]`. Both `max_swe_difference_kg_m2` and `max_albedo_difference` > 0.
