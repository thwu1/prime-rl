Two CMORization pipelines convert raw observational NetCDFs in `/app/raw_data/` to CMIP6 Amon-compliant format per the CMOR table specification at `/app/cmor_spec.json`:

- **Pipeline Alpha**: `/app/pipeline_alpha/cmorize.py` → `/app/output_alpha/`
- **Pipeline Beta**: `/app/pipeline_beta/cmorize.py` → `/app/output_beta/`

The raw data comprises three variables (`tas`, `pr`, `rlut`) on heterogeneous source grids and encodings — a 360-day calendar, a Gaussian-like latitude grid, undeclared sentinel fill values, non-CF unit strings, and coordinate ranges requiring transformation. Each pipeline correctly handles a different subset of CMOR/CF-1.8 compliance requirements while introducing distinct defects in the remainder. Some defects are coupled through processing order: the sequence in which coordinate transformations, unit conversions, and fill-value masking are applied determines whether data integrity is preserved or silently corrupted.

Perform a comprehensive CMOR/CF-1.8 compliance audit by examining both pipelines' source code and output files against the CMOR specification and CF metadata conventions. This requires understanding coordinate transformation semantics (the coupling between coordinate reordering and data array reordering), physical unit conversion arithmetic and direction, fill-value detection in the presence of data transformations, Gaussian vs. regular grid boundary computation for polar coverage, temporal bound requirements for monthly data, and the CF-1.8 metadata convention for global and variable attributes.

**Deliverables:**

Write `/app/audit_report.json` conforming to this schema:

```
{
  "pipeline_alpha": {
    "spatial_alignment": <bool>,
    "unit_conversion": <bool>,
    "unit_strings": <bool>,
    "lat_bounds_polar": <bool>,
    "time_bounds": <bool>,
    "missing_values": <bool>,
    "global_attributes": <bool>,
    "variable_attributes": <bool>,
    "pass_count": <int>,
    "defect_analysis": {
      "<failing_dimension>": {
        "root_cause": "<one-sentence code-level explanation of the defect>",
        "affected_variables": ["<var>", ...]
      }
    }
  },
  "pipeline_beta": { ... same structure ... },
  "processing_dependencies": [
    {
      "earlier": "<operation that must come first>",
      "later": "<operation that must come second>",
      "rationale": "<why this ordering is critical, referencing observed pipeline behavior>"
    }
  ],
  "superior_pipeline": "alpha" | "beta" | "neither"
}
```

Each boolean indicates whether that pipeline correctly handles the named compliance property. `pass_count` is the total `true` count. `defect_analysis` must contain an entry for each dimension where the boolean is `false`, with a root cause that references the specific algorithmic flaw and lists all variables affected by it. `processing_dependencies` must identify at least two ordering constraints critical to correct CMORization and explain, with reference to the observed pipeline defects, how violating each constraint corrupts the output.

Create `/app/cmorize_final.py` — a corrected pipeline synthesizing the correct approaches from both implementations — and run it to produce fully CMOR-compliant output for all three variables in `/app/output/` as `{var}_Amon_OBS_2001.nc`.