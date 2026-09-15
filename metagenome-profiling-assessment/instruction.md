Build a Makefile-driven pipeline at `/app/Makefile` that evaluates taxonomic profiling predictions against a gold standard using Bioboxes profiling format v0.10.0.

**Invocation**:
```
make -C /app all MANIFEST=/app/data/manifest.json OUTPUT_DIR=/app/output
```

The manifest JSON specifies `gold_standard`, `predictions` (each with `file` and `label`), and `taxonomy` — all paths relative to the manifest's directory. Reference files `/app/data/reference_metrics.tsv` and `/app/data/reference_rankings.tsv` provide verified ground-truth outputs for a subset of the data; reproduce these within tolerance 1e-4.

The Makefile must accept `MANIFEST` and `OUTPUT_DIR` as variables and expose a `taxonomy-db` target that creates the SQLite database independently of other outputs.

**Required outputs in `$(OUTPUT_DIR)/`**:

`taxonomy.db`: SQLite database. Table `nodes` with columns `tax_id` (INTEGER PRIMARY KEY), `parent_id` (INTEGER), `rank` (TEXT). Populated from the NCBI nodes.dmp taxonomy file (tab-pipe-tab delimited). Every entry in the source file must appear.

`results.tsv`: TSV with columns: `tool`, `sample`, `rank`, `l1_norm`, `bray_curtis`, `precision`, `recall`, `f1`, `jaccard`, `shannon_diversity`. One row per (tool, sample, rank) combination where samples and ranks come from the gold standard. Sorted by tool alphabetically, then sample ID, then rank in the order from the gold standard's `@Ranks` header. Numerics to 6 decimal places. Ranges: l1_norm in [0,2]; bray_curtis, precision, recall, f1, jaccard in [0,1]; shannon_diversity >= 0.

`rankings.tsv`: TSV with columns: `tool`, `avg_l1_norm`, `avg_bray_curtis`, `avg_precision`, `avg_recall`, `avg_f1`, `avg_jaccard`, `composite_score`. Each `avg_*` is the mean across all (sample, rank) pairs for that tool. Derive `composite_score` from the reference data. Sorted by `composite_score` descending. composite_score in [0,1]. 6 decimal places.

`validation.json`: JSON with key `"warnings"` — a list of objects with fields `"file"` (profile basename), `"sample"`, `"rank"`, `"issue"`. Check all input profiles (gold standard and predictions) for: (a) any rank where the percentage sum deviates from 100.0 by more than 0.1, and (b) any TAXPATH whose implied parent-child relationship is inconsistent with `taxonomy.db`. Well-formed profiles must not generate false positive warnings.

**Data handling rules**:
- Comment lines (`#`-prefixed) interspersed in data sections: skip.
- Duplicate TAXID entries within the same sample and rank: merge by summing percentages.
- Zero-abundance entries (0.0%): exclude from presence/absence metrics.
- Missing sample (present in gold standard but absent from a prediction file): l1_norm=1.0, bray_curtis=1.0, precision=recall=f1=jaccard=shannon_diversity=0.0.
- Shannon diversity: computed from the prediction profile using percentage/100 as probabilities (not renormalized to sum to 1).
