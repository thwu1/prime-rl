Audit taxonomic profiling submissions for a metagenomics benchmarking challenge. Five tools submitted CAMI Bioboxes format predictions for two metagenomic samples. Not all submissions are clean — diagnose and document any data quality issues, produce corrected evaluation metrics, and rank the tools.

## Inputs

- `/opt/taskdata/taxonomy/` — NCBI taxonomy dump files (`nodes.dmp`, `names.dmp`, `merged.dmp`)
- `/opt/taskdata/gold_standard.profile` — Gold standard taxonomic profiles (CAMI Bioboxes profiling format)
- `/opt/taskdata/submissions/` — Profiler predictions: `profiler_alpha.profile` through `profiler_echo.profile`

## Outputs

### `/app/audit/opal_output/`
OPAL (`cami-opal`) evaluation output from running the submissions against the gold standard.

### `/app/audit/issues.json`
JSON array of data quality issues found. Each element: `{"tool": "<name>", "sample": "<id>", "issue_type": "<category>", "description": "<details>"}`.

### `/app/audit/corrected_metrics.tsv`
Tab-separated post-correction evaluation. Columns: `tool`, `sample`, `rank`, `l1_norm`, `precision`, `recall`. One row per (tool, sample, rank) combination across all 5 tools, 2 samples, and 7 standard ranks (superkingdom, phylum, class, order, family, genus, species). L1 norm = sum of |predicted - gold| over union of taxa at the rank. Precision/recall based on taxon presence.

### `/app/audit/ranking.txt`
Profiler names, one per line, best to worst by mean corrected L1 across all samples and ranks.