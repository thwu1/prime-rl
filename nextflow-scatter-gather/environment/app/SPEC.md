# Pipeline Specification

## Overview

This pipeline performs multi-path quality assessment of measurement data. Samples are
routed to different analysis processes based on their priority level, then results are
aggregated by experiment and evaluated against reference values.

## Input Data

### Samplesheet (`samplesheet.csv`)

CSV with columns: `sample_id`, `experiment`, `priority`, `data_file`

- `priority` is either `high` or `low`
- `data_file` is a path relative to the project directory pointing to a TSV measurement file

### Measurement Files (`data/*.tsv`)

Tab-separated with three columns (no header): `measurement_id`, `value`, `quality_score`

- `value` is a floating-point measurement value
- `quality_score` is a float in the range [0, 1]

### Reference (`reference.csv`)

CSV with columns: `experiment`, `expected_mean`, `tolerance`

## Processing Rules

### High-Priority Samples (DETAILED_ANALYSIS)

For samples where `priority` equals `high`:

1. Read all measurements from the sample's data file
2. Compute the **quality-weighted mean**: `sum(value * quality_score) / sum(quality_score)`
3. Record the total measurement count (number of rows in the file)
4. Write a single-line CSV to the output file with format:
   `sample_id,experiment,high,mean,count`

### Low-Priority Samples (QUICK_ANALYSIS)

For samples where `priority` equals `low`:

1. Read all measurements from the sample's data file
2. **Discard** any measurement where `quality_score < 0.5`
3. Compute the **simple arithmetic mean** of the remaining values
4. Record the count of retained measurements
5. Write a single-line CSV to the output file with format:
   `sample_id,experiment,low,mean,count`

### Experiment Aggregation (AGGREGATE_EXPERIMENT)

For each experiment (grouping all samples that share the same experiment identifier):

1. Read all per-sample result files produced by the analysis processes
2. Compute the **count-weighted grand mean**: `sum(sample_mean * sample_count) / sum(sample_count)`
3. Compute `total_measurements` = sum of all sample counts
4. Compute `num_samples` = number of distinct samples
5. Count how many samples were high-priority (`high_priority_count`) and low-priority (`low_priority_count`)
6. Write a JSON object to the output file containing: `experiment`, `num_samples`,
   `total_measurements`, `grand_mean` (full precision), `high_priority_count`, `low_priority_count`

### Experiment Evaluation (EVALUATE_EXPERIMENT)

For each experiment:

1. Read the aggregated JSON produced by AGGREGATE_EXPERIMENT
2. Compute `deviation = abs(grand_mean - expected_mean)` using the full-precision grand_mean
3. Determine `within_tolerance = (deviation <= tolerance)`
4. Round `grand_mean` to 2 decimal places
5. Round `deviation` to 2 decimal places
6. Write a JSON object to the output file containing all fields from the aggregate plus:
   `expected_mean`, `deviation`, `tolerance`, `within_tolerance`

## Output Format

The pipeline must produce `results/report.json` (relative to the project directory)
containing a JSON array **sorted alphabetically by experiment name**. Each element is
an object with exactly these fields:

| Field                | Type    | Description                                              |
|----------------------|---------|----------------------------------------------------------|
| `experiment`         | string  | Experiment identifier                                    |
| `num_samples`        | integer | Number of samples in this experiment                     |
| `total_measurements` | integer | Sum of measurement counts across all samples             |
| `grand_mean`         | float   | Count-weighted grand mean, rounded to 2 decimal places   |
| `expected_mean`      | float   | Reference expected mean value                            |
| `deviation`          | float   | abs(grand_mean - expected_mean), rounded to 2 decimal places |
| `tolerance`          | float   | Reference tolerance threshold                            |
| `within_tolerance`   | boolean | Whether the unrounded deviation is within tolerance      |
| `high_priority_count`| integer | Number of high-priority samples in the experiment        |
| `low_priority_count` | integer | Number of low-priority samples in the experiment         |
