Four PROJ `gie` test files at `/app/` define coordinate transformations with incorrect projection or datum parameters. Each file contains GIGS (Geospatial Integrity of Geoscience Software) reference coordinate pairs representing the known-correct output. Currently all four files fail when run through the `gie` tool.

**Task:**

1. Diagnose and correct the parameter errors in `scenario_a.gie`, `scenario_b.gie`, `scenario_c.gie`, and `scenario_d.gie` so every test case passes when validated with `gie`. Write the corrected files to `/app/results/scenario_a_fixed.gie` through `/app/results/scenario_d_fixed.gie`.

2. Construct a PROJ coordinate transformation that converts geographic coordinates on the DHDN datum (Bessel ellipsoid) to ETRS89-LAEA Europe projected coordinates, chaining the corrected Helmert 7-parameter datum shift from Scenario D with the corrected LAEA projection from Scenario C. Apply this transformation to the five coordinate pairs in `/app/chain_input.csv` and write results to `/app/results/chain_results.csv` with columns: `lon_dhdn,lat_dhdn,easting_laea,northing_laea` (easting and northing rounded to 2 decimal places).

PROJ tools (`gie`, `cs2cs`, `cct`, `projinfo`, `geod`) are installed at standard system paths.