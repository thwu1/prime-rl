Five building sites in the western United States need a seismic hazard assessment that determines whether their ASCE 7-22 code-based design parameters are consistent with recently observed earthquake activity in the surrounding region.

## Inputs

- Building sites: `/app/sites.json`
- Output schemas: `/app/output_schemas.json`

## Data Scope

Analyze M2.5+ earthquakes from 2024-01-01 through 2024-03-31 in the region 32°N–49°N, 125°W–105°W. Earthquake catalog data is available from the USGS FDSN Event web service (`earthquake.usgs.gov/fdsnws/event/1/`). ASCE 7-22 design parameters can be retrieved from the USGS Design Maps web service (`earthquake.usgs.gov/ws/designmaps/`) using risk category II and site class D.

## Deliverables

Write JSON files to `/app/output/`, conforming to the schemas in `/app/output_schemas.json`:

- **`catalog_summary.json`** — Summary statistics for the retrieved earthquake catalog.

- **`grid_bvalues.json`** — Gutenberg-Richter frequency-magnitude parameters computed on a 1°×1° spatial grid. Include only cells with at least 10 events. Each cell must have an estimated completeness magnitude, b-value with standard error, and annualized a-value.

- **`site_design.json`** — ASCE 7-22 spectral acceleration parameters and seismic design category for each building site.

- **`site_activity.json`** — Observed earthquake activity within a 200 km radius of each site: event counts, maximum observed magnitude, nearest event distance, and annualized rates for all events and M4+ events.

- **`discrepancy.json`** — Per-site hazard consistency assessment. The discrepancy ratio is `(annualized_rate × max_observed_magnitude / 10) / SDS`. Classify each site as `observed_exceeds_design` (ratio > 2.0), `design_exceeds_observed` (ratio < 0.1), `consistent` (0.1 ≤ ratio ≤ 2.0), or `insufficient_data` (when required values are missing).