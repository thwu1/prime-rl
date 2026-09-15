A LAMMPS-based elastic constants workflow at `/app/elastic_workflow/compute_elastic.py` computes elastic constants and derived mechanical properties of silicon using the Stillinger-Weber (SW) interatomic potential via finite-difference stress-strain analysis. The workflow runs to completion without runtime errors but produces incorrect results: some elastic constants deviate significantly from known values, several derived quantities are unimplemented (output as 0.0), and at least one derived property formula is wrong.

LAMMPS is available as `lmp`. The SW potential file is at `/app/potentials/Si.sw`.

Analyze the workflow's output and source code, diagnose all issues (bugs in the simulation pipeline, incorrect physical assumptions, wrong formulas, and missing implementations), fix them, and produce correct results in `/app/results.json` with exactly these keys (values in GPa unless dimensionless):

```json
{
  "C11": ..., "C12": ..., "C44": ...,
  "bulk_modulus": ...,
  "shear_modulus_voigt": ..., "shear_modulus_reuss": ..., "shear_modulus_hill": ...,
  "youngs_modulus_100": ..., "youngs_modulus_111": ...,
  "poisson_ratio": ...,
  "zener_anisotropy": ...,
  "cauchy_pressure": ...
}
```

Reference: the published elastic constants of SW silicon are approximately C11 ~ 151 GPa, C12 ~ 76 GPa, C44 ~ 56 GPa (Cowley, Phys. Rev. B, 1988). All derived quantities must be physically meaningful, self-consistent with the computed elastic constants, and use polycrystalline (Hill) averaging where applicable.