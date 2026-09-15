# Pipeline Architecture

## Overview

The analysis pipeline processes multi-format coverage data through three
stages, each using a different tool. The pipeline is orchestrated by
`/app/tools/pipeline.sh`.

## Stage 1: Configuration Extraction

**Script**: `/app/tools/extract_config.sh`
**Tool**: `sqlite3`

Queries the SQLite experiment database (`/app/data/experiment.db`) for analysis
parameters (Tversky-index coefficients, edge space size). Outputs a JSON
configuration file to `/tmp/pipeline_config.json` for use by downstream stages.

## Stage 2: Core Analysis

**Script**: `/app/tools/analysis.py`
**Tool**: `python3`

Reads the pipeline configuration from `/tmp/pipeline_config.json` and experiment
metadata from `/app/data/meta.json`. Loads coverage data from two sources:

- **FCOV binary files** for benchmarks listed in `meta.json`'s `fcov_benchmarks`
- **SQLite database** for benchmarks listed in `meta.json`'s `db_benchmarks`

Computes novelty coverage scores, cross-benchmark aggregate rankings, pairwise
statistical tests (Mann-Whitney U with Benjamini-Hochberg correction), and
coverage velocity. Writes output JSON files to `/app/output/`.

## Stage 3: Output Formatting

**Filter**: `/app/tools/format_ranking.jq`
**Tool**: `jq`

Post-processes `/app/output/aggregate_ranking.json` to enforce schema-compliant
numeric precision and field structure.

## Running the Pipeline

Execute all stages in sequence:
```
/app/tools/pipeline.sh
```

Or run individual stages manually for debugging.
