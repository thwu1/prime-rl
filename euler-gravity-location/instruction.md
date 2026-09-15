The file `/app/survey.csv` contains 500 scattered gravity observations from a terrain-following airborne survey over a 10 km x 10 km area. Columns: `easting` (m), `northing` (m), `height` (m above surface), `gz_mGal` (downward gravitational acceleration in mGal). Observations are at varying heights (100-500 m) with measurement noise (sigma ~ 0.002 mGal). The underlying gravity field is produced by several buried point masses whose positions and magnitudes are unknown.

The file `/app/prediction_grid.csv` specifies a regular 51x51 grid at uniform 500 m altitude with 200 m horizontal spacing. Columns: `easting`, `northing`, `height`.

## Task

Create `/app/eqs_pipeline.py` that continues the observed gravity field onto the prediction grid using an equivalent-source method. The script accepts four positional arguments:

    python3 /app/eqs_pipeline.py [survey_csv] [grid_csv] [output_csv] [diagnostics_json]

Defaults: `/app/survey.csv`, `/app/prediction_grid.csv`, `/app/predictions.csv`, `/app/diagnostics.json`.

The method must place fictitious point masses below the survey locations, construct the gravitational forward operator in three dimensions (accounting for the varying observation heights), solve a regularized inverse problem for the source coefficients, and predict the field at the grid locations. Both the equivalent-source depth and the regularization (damping) parameter must be selected by automated model selection (e.g., generalized cross-validation) -- they must not be hardcoded to the provided dataset. Prediction uncertainties must be propagated from the observation noise through the regularized inverse.

## Outputs

**`predictions.csv`**: columns `easting,northing,gz_predicted,gz_uncertainty` -- one row per grid point (2601 total). `gz_uncertainty` is the standard deviation of each prediction arising from observation noise propagated through the inverse.

**`diagnostics.json`**: at minimum the keys `damping` (float > 0), `rms_misfit` (mGal), `source_depth` (m, > 0), `n_sources` (int), `mean_prediction_uncertainty` (mGal).

## Evaluation

- Primary dataset: predicted field must have RMS error < 0.02 mGal versus the true (noise-free) field at the grid altitude.
- A secondary survey (different subsurface sources, different observation locations) will be generated at test time. The same pipeline must achieve RMS error < 0.03 mGal on that dataset.
- Diagnostics must be physically reasonable. Prediction uncertainties must be finite and positive.