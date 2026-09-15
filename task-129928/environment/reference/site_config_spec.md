# Site Configuration Specification

The `site_parameters` table in the clinical database stores site-specific
evaluation parameters. Each parameter is identified by the combination
of `site_code` and `parameter_name`.

## Key Parameters

### min_followup_years

The minimum follow-up duration (in years) required for a patient to be
classified as Group 2 (CI-negative). This threshold accounts for the
varying data availability across contributing sites.

To determine a patient's follow-up eligibility for Group 2 classification,
look up the `min_followup_years` parameter for their site and verify that
their follow-up duration (from PSG date to last known visit) meets or
exceeds this threshold.

If no site-specific parameter is found, use the default threshold of
7.0 years.

## Schema

```
site_parameters(
    param_id INTEGER PRIMARY KEY,
    site_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    parameter_value TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    notes TEXT
)
```

Indexed on (site_code, parameter_name) for efficient lookups.
