Two LAMMPS input scripts in `/app/` (`in.heat` and `in.mp`) are intended to compute the thermal conductivity (κ) of a Lennard-Jones fluid at ρ\* = 0.6, T\* = 1.35, r\_c = 2.5σ using two independent NEMD methods (fix heat and Müller-Plathe). The system is 8000 atoms on an FCC lattice (10×10×20 unit cells), periodic boundaries, LJ units. The established reference value for this state point is κ ≈ 3.4 in LJ units (Evans, Phys Rev A 34, 1449, 1986).

Both scripts run without LAMMPS errors but produce κ values that are clearly inconsistent with the reference. Investigate the scripts to identify and correct all issues, re-run the corrected simulations, and produce verified results.

Write results to `/app/results.json`:

```
{
  "kappa_method1": <float, κ from in.heat in LJ units>,
  "kappa_method2": <float, κ from in.mp in LJ units>,
  "kappa_avg_lj": <float, arithmetic mean of both in LJ units>,
  "kappa_si": <float, average κ in W/(m·K) for Argon>,
  "argon_params": {
    "epsilon_J": <float, ε in Joules>,
    "sigma_m": <float, σ in meters>,
    "mass_kg": <float, atomic mass in kg>,
    "tau_s": <float, LJ time unit τ = σ·√(m/ε) in seconds>
  }
}
```

Argon LJ parameters: ε/k\_B = 119.8 K, σ = 3.405 Å, m = 39.948 amu.

LAMMPS is pre-installed as `lmp`. Work in `/app/`.