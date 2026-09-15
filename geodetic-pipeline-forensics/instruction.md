A European spatial data infrastructure project requires accuracy evaluation of coordinate transformation workflows. For each scenario, multiple candidate PROJ pipeline configurations exist with differing parameterizations. Derive reference coordinates from the authoritative CRS definition provided (method name, EPSG method code, parameters, and ellipsoid), evaluate every candidate against them, produce a ranked accuracy assessment with tier classification, and — for a separate scenario where no pipeline is provided — identify an unknown map projection and design a working transformation pipeline from raw surveyed control observations.

## Input Data

`/app/scenarios.json` contains:

- **`accuracy_tiers`**: Three quality tiers with maximum RMSE thresholds — survey-grade, mapping, and navigation.
- **`evaluation_scenarios`**: Three named scenarios (`oblique_stereo`, `laea_europe`, `geocentric`), each with a `reference_definition` (EPSG method code, parameter table with EPSG parameter names, and ellipsoid specification), multiple named candidate PROJ pipeline strings, and geographic input points. No pre-computed reference output coordinates are provided — you must construct the authoritative PROJ pipeline from the reference definition and generate reference coordinates yourself.
- **`design_scenario`**: Points to `/app/survey_observations.csv` containing paired geographic and projected coordinates from an unidentified map projection. No pipeline, EPSG code, or projection name is given.

PROJ CLI tools (`cct`, `cs2cs`, `projinfo`, `gie`) are available.

## Deliverables

Write all results to `/app/results/`:

- **`accuracy_report.json`** — For each evaluation scenario and each candidate: `rmse_m` (root-mean-square positional error in meters) and `max_error_m` (maximum positional error in meters). Positional error at each point is the Euclidean distance between the candidate's `cct` output and the reference coordinates derived from the authoritative CRS definition.

- **`tier_classification.json`** — For each evaluation scenario and each candidate: the highest accuracy tier met (`"survey"`, `"mapping"`, `"navigation"`, or `"none"`), based on the candidate's RMSE versus the thresholds in `accuracy_tiers`.

- **`rankings.json`** — For each evaluation scenario: `"ranking"` (array of candidate names ordered best-to-worst by RMSE) and `"survey_recommendation"` (name of the best candidate that meets survey-grade, or `null` if none qualifies).

- **`designed_pipeline.json`** — For the design scenario: `"proj_string"` (a valid PROJ string that transforms the geographic coordinates to the projected coordinates within 0.05 m tolerance on all control points) and `"projection_type"` (the identified map projection type).