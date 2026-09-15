A national oceanographic data archive has rejected the dataset at `/app/ocean_station.nc`. The file contains one year of daily measurements (temperature, salinity, pressure, currents, dissolved oxygen, chlorophyll, turbidity) at 20 depth levels from a moored ocean station, but it fails validation against the CF-1.6 and ACDD-1.3 metadata standards. The `compliance-checker` tool is installed and available at the command line.

Produce two deliverables:

1. **`/app/ocean_station_fixed.nc`** — A corrected copy of the dataset that achieves:
   - CF-1.6 weighted compliance ratio (scored_points / possible_points) >= 0.92
   - ACDD-1.3 weighted compliance ratio >= 0.87
   - All original scientific measurement data arrays preserved with byte-identical values (no resampling, scaling, or imputation)
   - Valid netCDF4 format

2. **`/app/compliance_audit.json`** — A structured JSON audit documenting your analysis:
   - `"baseline"`: object with keys `"cf_1_6"` and `"acdd_1_3"`, each containing `"scored_points"` (number) and `"possible_points"` (number) from running the checker against the **original** file
   - `"remediated"`: same structure, from running the checker against the **fixed** file
   - `"violations"`: array of objects, each with:
     - `"scope"`: affected variable name or `"global"` for file-level attributes
     - `"standard"`: `"CF-1.6"` or `"ACDD-1.3"`
     - `"priority"`: `"high"`, `"medium"`, or `"low"` — your assessment of how much this violation impacts the weighted compliance score
     - `"issue"`: what was wrong
     - `"resolution"`: what was done to fix it

The audit baseline scores must accurately reflect the checker's actual output on the original file, and the remediated scores must accurately reflect the checker's output on the fixed file.