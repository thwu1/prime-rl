A multi-period probabilistic seismic hazard model for Southern California is defined at `/app/model/`. The model comprises point sources and fault sources (including a 45-degree-dipping thrust with specified depth range) in namespaced XML, a period-dependent ground motion model with epistemic logic tree branches in SQLite, site characterization with basin depth parameters in GeoJSON, and calculation settings in TOML. See `/app/model/README.md` for the file inventory and database schema.

Analyze all model data and implement a complete multi-period PSHA computation. Write results to `/app/output/`:

- **`hazard_PGA.csv`**, **`hazard_SA0P2.csv`**, **`hazard_SA1P0.csv`** -- Hazard curves (annual exceedance rates) at each configured intensity measure level for every site. Header: `site,<iml_1>,<iml_2>,...`. Data rows: `<site_name>,<rate_1>,<rate_2>,...` (scientific notation, e.g. `1.234e-02`).

- **`uhs.csv`** -- Uniform hazard spectra at the configured return periods. Header: `site,return_period,PGA,SA0P2,SA1P0`. One row per site per return period, spectral ordinates interpolated from each period's hazard curve independently in log-log space.

- **`deaggregation.csv`** -- Magnitude-distance deaggregation for the IMT, site, and return period given in config. Columns: `metric,value`. Rows: `mean_M`, `mean_R`, `mode_M`, `mode_R` (mode = center of the bin with highest contribution).

The GMM functional form, its required distance metric, and reference parameters are stored in the database `metadata` table. Coefficients are indexed by both branch and spectral period. The correct source-to-site distance must be derived from the stated metric and computed appropriately for each source geometry -- point source depths matter, and fault dip plus depth range define a 3D rupture plane. Basin depth site parameters affect long-period ground motion through the period-dependent GMM coefficients.