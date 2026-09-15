The SQLite database at `/app/monitoring.db` contains three years (2022-2024) of EPA Air Quality System (AQS) annual monitoring summary data for criteria pollutant monitors across multiple states. The database schema is undocumented -- explore it with `sqlite3`.

The monitoring network configuration at `/app/data/monitor_config.xml` is an XML registry exported from the AQS network management system. It describes each monitor's method designation (FRM, FEM, ARM, etc.), monitoring objective, and operational status. Not all monitors in the database are eligible for regulatory compliance determination -- the registry identifies each monitor's classification. This file uses XML namespaces.

Reference materials:
- `/app/data/naaqs_standards.psv` -- Pipe-delimited NAAQS standards reference (with header). Includes both current and superseded standards, statistical form definitions, decimal reporting conventions, and compliance method types.
- `/app/docs/naaqs_design_value_guidance.txt` -- EPA regulatory reference covering design value methodology, monitor eligibility criteria, event type handling, data completeness requirements, and compliance determination procedures for all criteria pollutants.

Previous automated compliance assessments are archived at `/app/audit/state_reports.tar.gz`. This gzipped tarball contains per-state JSON files under a `state_reports/` directory, each named by two-digit state FIPS code (e.g., `state_reports/04.json`). Each file has a `monitors` array with that state's assessment entries. EPA regional reviewers have determined these reports contain multiple methodological errors affecting design value computations and compliance determinations across several pollutants.

Produce two output files:

**`/app/output/compliance_report.json`** -- Corrected NAAQS compliance assessment for the 2022-2024 period, structured as `{"monitors": [...]}`. Determine which monitors are eligible for regulatory compliance assessment, compute design values using the correct pollutant-specific statistical forms and decimal conventions, and apply compliance determination rules for all applicable monitor-standard combinations. Only include current (non-superseded) standards and eligible primary monitors with valid event classifications. The database does not include explicit column-to-statistic mappings; use the statistical form descriptions in the standards reference together with the database schema to determine which data fields correspond to each standard's design value computation.

Each entry:
```json
{
  "site_id": "SS-CCC-NNNN",
  "parameter_code": 44201,
  "parameter_name": "Ozone",
  "pollutant_standard": "Ozone 8-hour 2015",
  "design_value": 0.070,
  "naaqs_level": 0.070,
  "units": "ppm",
  "status": "Meeting"
}
```

`site_id` format is `state_code-county_code-site_num` with zero-padding preserved. `naaqs_level` and `units` must reflect the actual compliance comparison being made for that standard's form. Status is `"Meeting"`, `"Exceeding"`, or `"Insufficient Data"` as determined by the regulatory methodology. Sort entries by `site_id`, then `parameter_code`, then `pollutant_standard`.

**`/app/output/error_analysis.json`** -- Documentation of errors found in the previous reports, structured as `{"errors": [...]}`. Compare your corrected computations against the archived reports to identify methodological errors. Find at least 4 distinct errors spanning at least 3 different `parameter_code` values. Each entry:

```json
{
  "affected_monitor": "SS-CCC-NNNN",
  "parameter_code": 44201,
  "error_category": "...",
  "previous_value": "...",
  "corrected_value": "...",
  "explanation": "..."
}
```