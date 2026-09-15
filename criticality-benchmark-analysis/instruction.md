Three ICSBEP criticality safety benchmark experiments are provided under `/app/`, together with pre-computed Monte Carlo neutron-transport simulation results and an experimental reference database.

**Benchmark models** (`/app/benchmarks/`):
- `hmf001/` — HEU-MET-FAST-001 (Godiva): bare HEU metal sphere modeled as 6 concentric uranium shells separated by air gaps
- `hmf003/` — HEU-MET-FAST-003 (Topsy): HEU sphere with a natural-uranium reflector
- `hst001/` — HEU-SOL-THERM-001: uranyl nitrate solution in a stainless-steel cylinder
- `uncertainties.csv` — experimental k-effective reference data

**Simulation statepoints** (`/app/statepoints/`): HDF5 files containing per-batch eigenvalue results from Monte Carlo criticality calculations, one file per benchmark.

Produce `/app/validation_report.json` with the structure below.

```json
{
  "hmf001": {
    "total_fissile_mass_kg": "<float>",
    "avg_enrichment_wt_pct": "<float>",
    "shell_densities_gcc": ["<6 floats, innermost to outermost>"],
    "simulated_keff": "<float>",
    "simulated_keff_stderr": "<float>",
    "n_active_batches": "<int>",
    "entropy_converged": "<bool>",
    "experimental_keff": "<float>",
    "experimental_uncertainty": "<float>",
    "c_over_e": "<float>",
    "c_over_e_unc": "<float>",
    "validation_pass": "<bool>"
  },
  "hmf003": {
    "core_mass_kg": "<float>",
    "core_enrichment_wt_pct": "<float>",
    "reflector_mass_kg": "<float>",
    "reflector_enrichment_wt_pct": "<float>",
    "core_density_gcc": "<float>",
    "reflector_density_gcc": "<float>",
    "simulated_keff": "<float>",
    "simulated_keff_stderr": "<float>",
    "n_active_batches": "<int>",
    "entropy_converged": "<bool>",
    "experimental_keff": "<float>",
    "experimental_uncertainty": "<float>",
    "c_over_e": "<float>",
    "c_over_e_unc": "<float>",
    "validation_pass": "<bool>"
  },
  "hst001": {
    "solution_density_gcc": "<float>",
    "enrichment_wt_pct": "<float>",
    "hx_ratio": "<float>",
    "solution_volume_cm3": "<float>",
    "u235_mass_g": "<float>",
    "simulated_keff": "<float>",
    "simulated_keff_stderr": "<float>",
    "n_active_batches": "<int>",
    "entropy_converged": "<bool>",
    "experimental_keff": "<float>",
    "experimental_uncertainty": "<float>",
    "c_over_e": "<float>",
    "c_over_e_unc": "<float>",
    "validation_pass": "<bool>"
  }
}
```

- `c_over_e`: calculated-to-experimental k-effective ratio.
- `c_over_e_unc`: its propagated uncertainty.
- `validation_pass`: true if C/E is consistent with unity at 95% confidence.
- `entropy_converged`: true if the Shannon entropy history indicates fission-source stationarity.