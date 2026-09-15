The dataset at `/app/data/sst_anomaly.nc` contains synthetic sea surface temperature anomalies (variable `sst_anomaly`, dimensions `time x lat x lon`, NaN-masked land points). An analysis pipeline at `/app/pipeline/analyze.py` performs EOF decomposition with Varimax rotation and bootstrap significance testing. Its output is at `/app/pipeline/output/results.json`.

Independent verification has determined that the pipeline's output is incorrect. Multiple bugs are present across different stages of the analysis. The number, location, and nature of the errors are for you to determine.

Investigate the pipeline, identify and correct all errors, and produce valid results at `/app/results/eof_results.json` with the following JSON schema:

- `n_modes_computed` (int)
- `explained_variance_ratios` (list[float])
- `cumulative_variance` (list[float])
- `n_modes_rotated` (int)
- `rotation_matrix` (list[list[float]])
- `rotated_explained_variance_ratios` (list[float], sorted descending)
- `n_significant_modes` (int)
- `bootstrap_eigenvalue_ci` (list[list[float]], each `[lower, upper]`)

The corrected results must be consistent with the underlying dataset and satisfy standard mathematical properties of EOF analysis.