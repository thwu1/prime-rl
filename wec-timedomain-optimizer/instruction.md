Create `/app/wec_sim.py` that reads `/app/config.json` and `/app/hydro_data.json`, simulates a heaving wave energy converter across multiple sea states, optimizes PTO damping under motion constraints, and writes `/app/results.json`. Run with `python3 /app/wec_sim.py`.

**Input files**

`/app/hydro_data.json` provides frequency-domain hydrodynamic coefficients for a heaving hemisphere: angular frequencies `omega` (rad/s), added mass `A33` (kg), radiation damping `B33` (N·s/m), complex excitation force components `Fexc_re`/`Fexc_im` (N/m), and body properties (`mass`, `hydrostatic_stiffness`, `added_mass_inf`, `radius`).

`/app/config.json` defines `sea_states` (each with JONSWAP parameters, occurrence `probability`, `phase_seed`, frequency discretization), `simulation` settings (`dt`, `duration`, `ramp_time`), `pto` damping sweep range, `constraints.max_heave_amplitude` (meters), and `state_space` fitting parameters (`max_order`, `r2_threshold`, `irf_duration`, `irf_dt`).

**Requirements**

Convert frequency-domain radiation damping into a time-domain impulse response kernel and identify a continuous-time state-space realization {A, B, C}. Model order selected automatically via R² threshold, capped at `max_order`. All eigenvalues of A must have strictly negative real parts.

For each sea state, generate random-phase irregular wave excitation and integrate coupled body-radiation dynamics forward in time for every damping in the PTO sweep. Compute post-ramp (`t >= ramp_time`) heave statistics and average absorbed power per damping value.

PTO optimization produces two results: **unconstrained** (damping maximizing probability-weighted average power) and **constrained** (damping maximizing weighted power while peak post-ramp heave stays at or below `max_heave_amplitude` in every sea state, reporting which sea state IDs have binding constraints — heave within 5% of the limit).

**Output** `/app/results.json`:

```json
{
  "irf": {"time": [float], "K_r": [float], "K_r_at_zero": float},
  "state_space": {"order": int, "R2": float,
    "A": [[float]], "B": [[float]], "C": [[float]],
    "eigenvalues_real": [float]},
  "sea_states": {
    "<id>": {
      "wave": {"m0": float, "m2": float, "Hm0": float, "Tm02": float},
      "simulation": {"heave_max": float, "heave_std": float, "heave_mean": float},
      "power_curve": [[damping, avg_power], ...]
    }
  },
  "pto_optimization": {
    "unconstrained": {"optimal_damping": float, "weighted_avg_power": float},
    "constrained": {"optimal_damping": float, "weighted_avg_power": float, "binding_sea_states": [string]}
  }
}
```

Per-sea-state `simulation` fields use post-ramp data at the unconstrained optimal damping. Each `power_curve` entry is `[damping_Ns_m, avg_power_W]` matching the sweep grid.
