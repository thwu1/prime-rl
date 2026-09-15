EPA AQS annual summary data for air quality monitoring stations (2021-2023) is at `/app/data/annual_summary_2021_2023.csv` in the standard EPA AQS pre-generated annual summary format (55 columns per the AQS file format documentation).

Build a pipeline that computes NAAQS design values for every monitor in the dataset and determines compliance with current National Ambient Air Quality Standards. The dataset contains monitors for multiple criteria pollutants (O3, PM2.5, NO2, SO2, CO), each governed by a distinct standard with its own statistical form, design value column, and rounding/truncation convention. The pipeline must:

- Apply the correct pollutant-specific design value methodology — each standard uses a different column from the annual summary data (e.g., 4th max, arithmetic mean, 98th or 99th percentile, non-overlapping max), a different multi-year aggregation method, and a different precision rule (some standards truncate, others round)
- Compare computed design values to the correct NAAQS concentration levels
- Filter records appropriately based on exceptional event status — only use records where event data is properly excluded or no events occurred
- Flag monitors where the data completeness indicator shows insufficient coverage for a valid design value
- For sites with multiple Parameter Occurrence Codes (POCs) measuring the same pollutant under the same standard, report each POC's design value and identify the site-level (worst-case) design value

Write results to `/app/output/naaqs_compliance.json` with the following structure:

```json
{
  "assessment_period": "2021-2023",
  "monitors": [
    {
      "site_id": "SS-CCC-NNNN",
      "parameter_code": 44201,
      "parameter_name": "Ozone",
      "poc": 1,
      "standard": "Ozone 8-hour 2015",
      "naaqs_level": 0.070,
      "units": "ppm",
      "design_value": 0.073,
      "exceeds_standard": true,
      "data_complete": true
    }
  ],
  "site_level": [
    {
      "site_id": "SS-CCC-NNNN",
      "parameter_code": 44201,
      "standard": "Ozone 8-hour 2015",
      "design_value": 0.073,
      "worst_poc": 1,
      "exceeds_standard": true
    }
  ],
  "summary": {
    "total_monitor_assessments": 14,
    "exceeding": 8,
    "meeting": 6,
    "incomplete_data": 1
  }
}
```

The `monitors` array must have one entry per unique (site_id, parameter_code, poc, standard) combination. The `site_level` array must have one entry per unique (site_id, parameter_code, standard) combination, using the worst-case (highest design value) POC. Sort both arrays by site_id, then parameter_code, then standard, then poc.