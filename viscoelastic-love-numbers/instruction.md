The Fortran 90 source `/app/taboo.f90` implements the propagator-matrix method for computing viscoelastic Love numbers and normal-mode relaxation spectra for spherically symmetric, self-gravitating, incompressible Earth models with Maxwell rheology. The model specification is at `/app/model_spec.json`, which provides TABOO configuration parameters (layer count `nv`, model preset `code`, lithospheric thickness, mantle viscosities), the harmonic degree range, and a set of time evaluation points.

Running `python3 /app/pipeline.py` must produce these CSV files under `/app/output/`:

**`modes.csv`** — Physical relaxation modes. Header: `degree,mode_index,s_kyr_inv`. One row per physical mode (negative real eigenvalue only), sorted by degree ascending then `s_kyr_inv` ascending. `mode_index` is 0-based within each degree.

**`love_numbers.csv`** — Elastic and fluid-limit loading Love numbers. Header: `degree,h_elastic,h_fluid,l_elastic,l_fluid,k_elastic,k_fluid`. One row per harmonic degree in the specified range.

**`heaviside_h.csv`** — Heaviside-step response for vertical displacement Love number h. Header: `degree,t_kyr,value`. One row per (degree, time_point) combination for all degrees and all time points from `model_spec.json`. The Heaviside response at time t uses the normal-mode decomposition with elastic Love numbers and viscoelastic residues summed over physical modes only.

**`heaviside_l.csv`** — Same schema for horizontal displacement Love number l.

**`heaviside_k.csv`** — Same schema for gravitational potential Love number k.

Validation criteria:
- Elastic Love numbers: relative error < 1 × 10⁻⁶
- Fluid Love numbers: relative error < 1 × 10⁻⁵
- Relaxation rates: for each degree, all physical modes must be present with relative error < 1 × 10⁻³
- Heaviside response: relative error < 5 × 10⁻⁴ for values with |value| > 10⁻⁸; absolute error < 10⁻¹⁰ otherwise
- Every degree in the range must appear in all output files
