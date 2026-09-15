Multi-resolution ensemble data from a 2D dambreak simulation using Smoothed Particle Hydrodynamics is stored at `/app/data/` in SPHinXsys XML regression format. The dataset spans three spatial resolutions with reference baselines at each resolution. The ensemble contains members of varying quality.

Produce a comprehensive quality assessment at `/app/results.json` conforming to the schema in `/app/output_schema.md`. The assessment must evaluate run-to-reference time-series similarity, identify statistical outliers in the ensemble, compute ensemble convergence statistics with appropriate data cleaning, and determine the spatial convergence order of the numerical scheme.

Resources:
- `/app/data/` — simulation output and configuration
- `/app/data_format.md` — XML data format and directory layout
- `/app/output_schema.md` — required output JSON structure
- `/app/framework/` — SPHinXsys regression test framework source (reference)

Implement your analysis as `/app/sph_regression.py`. Both `make check` and the test suite must pass.