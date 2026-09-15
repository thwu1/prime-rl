The R pipeline at `/app/brdf_pipeline.R` (sourcing `/app/kernels.R`) processes MODIS MCD43A1 BRDF kernel parameters into surface albedo and reflectance products. Configuration is at `/app/config.json`; input data at `/app/data/input_params.csv`.

Running `Rscript /app/brdf_pipeline.R` must produce `/app/output/albedo_results.csv` with columns: `pixel_id`, `band`, `lat`, `lon`, `date`, `f_iso`, `f_vol`, `f_geo`, `bsa`, `wsa`, `bluesky`, `nbar`.

**Data filtering requirements:**

- Exclude rows where any raw kernel parameter equals the fill value from `config.json`.
- Retain only rows whose `quality` value is in the `valid_quality` list from `config.json`.
- Apply `scale_factor` from `config.json` to convert raw int16 parameters to physical units; `f_iso`, `f_vol`, `f_geo` in the output must be the scaled values.
- After correct filtering, the output must contain exactly 21 observations.

**Albedo product requirements:**

- BSA (Black-Sky Albedo), WSA (White-Sky Albedo), blue-sky albedo, and NBAR (Nadir BRDF-Adjusted Reflectance) must all be numerically correct per the RossThick-LiSparseReciprocal BRDF model as published by Lucht et al. (2000) and Schaaf et al. (2002).
- All albedo and NBAR values must be physically plausible (between -0.1 and 1.0).
- Blue-sky albedo must lie between BSA and WSA for each observation.
- The `compute_nbar` function currently returns `NA` for all rows. It must be fully implemented to produce valid NBAR values consistent with the MCD43A4 product definition, using the kernel model parameters specified in `config.json`.

The pipeline currently produces incorrect results across multiple output quantities. All defects in the R source files must be identified and corrected.
