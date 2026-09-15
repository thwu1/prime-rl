A seismic hazard model for a site in Northern California is distributed across four domain-standard geoscience file formats in `/app/data/`:

- `fault_sources.geojson` — OGR-compatible GeoJSON FeatureCollection containing fault source trace geometries with rupture parameters and embedded magnitude-frequency distribution (MFD) specifications in a JSON-encoded property field
- `grid_seismicity.nc` — NetCDF classic file containing gridded background seismicity point sources with Gutenberg-Richter parameters stored as 1D arrays over a point dimension
- `model.db` — SQLite database containing ground motion model (GMM) logic tree weights, regression coefficients, and a `metadata` table encoding the mathematical specifications for the PSHA computation (GMM functional form, distance metrics, coordinate approximations, MFD discretization scheme, exceedance probability formula, and the full hazard integral)
- `calc_config.yaml` — YAML configuration file specifying the computation site coordinates, Vs30, intensity measure levels, exceedance model, and truncation parameters

No schema documentation is provided for any of these formats. Inspect each file's internal structure using the appropriate CLI tools installed in the environment to discover field names, variable dimensions, table schemas, and embedded mathematical formulas before writing any computation code.

The data was assembled by merging entries from overlapping USGS regional earthquake catalogs and manual fault digitization records. It contains data quality issues that must be diagnosed and correctly handled before computation. Audit the data using domain expertise in probabilistic seismic hazard analysis (PSHA) to identify duplicate sources (identical geometry entered under different names), physically impossible parameter values, and inconsistent logic tree weights that do not form valid probability distributions.

Write two output files:

**`/app/output/hazard_curve.csv`** — CSV with header `iml,annual_rate` followed by exactly 20 data rows (one per IML in config order). The `annual_rate` column is the total mean annual rate of exceedance computed via the PSHA hazard integral over all valid deduplicated sources with properly normalized MFD logic tree branch weights. Values must be non-negative and monotonically non-increasing with increasing IML.

**`/app/output/validation_report.txt`** — Plain text file documenting each data quality issue found, one per line: duplicate sources identified and deduplicated, sources excluded due to physically invalid parameters, and any MFD weight normalization applied.