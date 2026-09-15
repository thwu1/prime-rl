A drag prediction workshop dataset at `/app/data/` contains results from 12 participants who each computed aerodynamic forces on a transonic wing-body configuration using three progressively refined meshes. The data is split across two files:

- `workshop.h5` — HDF5 file with force coefficients (CL, CD, CM) for each participant across three grid levels.
- `grid_metadata.db` — SQLite database with mesh node counts, solver metadata, and flow conditions for each participant and grid level.

Produce a rigorous grid convergence verification assessment in `/app/output/` containing these files:

**`continuum_estimates.csv`** — Grid-independent extrapolated values and observed convergence rates for each coefficient. Set to NaN where convergence is non-monotonic.
Columns: `participant_id,CD_extrapolated,CL_extrapolated,CM_extrapolated,p_CD,p_CL,p_CM`

**`uncertainty_bounds.csv`** — Numerical uncertainty on fine-grid CD with standard safety factor and asymptotic range check. Only participants with monotonic CD convergence.
Columns: `participant_id,GCI_fine_CD,GCI_coarse_CD,asymptotic_ratio_CD`

**`convergence_types.csv`** — Convergence behavior per coefficient classified as `monotonic`, `oscillatory`, or `divergent`.
Columns: `participant_id,CD_convergence,CL_convergence,CM_convergence`

**`ensemble_statistics.json`** — Ensemble summary of extrapolated CD (in drag counts, ×10⁴), excluding non-convergent and outlier participants.
Keys: `mean`, `std`, `median`, `iqr`, `n_valid`

**`outliers.json`** — Statistical outlier identification on extrapolated CD from monotonically-converged participants. JSON list of flagged entries with keys: `participant_id`, `chauvenet_flag` (bool), `modified_z_score` (float; flagged when |value| > 3.5).