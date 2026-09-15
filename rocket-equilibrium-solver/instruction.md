Create `/app/rocket_eq.py` that computes chemical-equilibrium rocket engine performance for the propellant system specified in `/app/problem.json`, using thermodynamic data from `/app/thermo_h2o2.dat`.

**Inputs:**

`/app/thermo_h2o2.dat` is a NASA 7-coefficient thermodynamic polynomial database in RP-1311 fixed-width format with Fortran `D` exponent notation. `/app/problem.json` specifies fuel and oxidizer properties (formulas, molecular weights, heats of formation, storage temperatures), O/F mass ratio, chamber pressure in bar, gas-phase product species to consider, and supersonic nozzle area ratios. `/app/thermo_eval.f90` is a Fortran 90 module providing `iso_c_binding`-compatible routines that evaluate Cp/R, H/(RT), S/R, and G/(RT) from the polynomial coefficients.

**Constraints:**

- Compile `/app/thermo_eval.f90` to a shared library and call its routines from Python via `ctypes` for all thermodynamic property evaluation. Do not reimplement polynomial evaluation in Python.
- Determine equilibrium combustion chamber conditions (temperature, composition, mean molecular weight) and nozzle throat and exit-plane properties at each specified supersonic area ratio.
- Report characteristic velocity and vacuum specific impulse for each exit station.
- Use only numpy, scipy, and the compiled Fortran library. No pre-built equilibrium packages (cea, Cantera, RocketCEA, etc.).

**Output:** Write `/app/results.json`:
```json
{
  "chamber": {
    "temperature_k": <float>,
    "pressure_bar": <float>,
    "molecular_weight": <float>,
    "mole_fractions": {"<species>": <float>, ...}
  },
  "throat": {
    "temperature_k": <float>,
    "pressure_bar": <float>
  },
  "performance": {
    "c_star_m_per_s": <float>,
    "exit_conditions": [
      {"area_ratio": <int>, "isp_vacuum_m_per_s": <float>}
    ]
  }
}
```

All species from `product_species` must appear in `mole_fractions`. Exit conditions must cover every `supersonic_area_ratios` entry, sorted ascending.

Run: `python3 /app/rocket_eq.py`
