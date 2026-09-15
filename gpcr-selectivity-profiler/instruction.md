Create `/app/profiler.py`, a Python CLI that builds pharmacological selectivity profiles by reconciling interaction data from the GtoPdb REST API and its downloadable interactions CSV.

API reference is at `/app/api_reference.txt`. Base URL: `https://www.guidetopharmacology.org/services/`
Interactions CSV: `https://www.guidetopharmacology.org/DATA/interactions.csv`

**CLI:** `python3 /app/profiler.py --targets <IDs> --species <S> --affinity-type <T> --min-targets <N> --output <path>`

- `--targets`: comma-separated GtoPdb target IDs (required)
- `--species`: species filter (default `Human`)
- `--affinity-type`: pKi / pIC50 / pEC50 / pKd (default `pKi`)
- `--min-targets`: minimum distinct targets a ligand must have valid data for (default `2`)
- `--output`: JSON output path (required)

Identify all ligands with affinity data for at least `min-targets` of the specified targets (filtered by species and affinity type). Reconcile data from both the REST API and the downloadable CSV. When multiple measurements exist for a ligand–target pair, report the median. Strip HTML markup from all name fields.

**Output JSON at `--output`:**

```json
{
  "query": {"targets": [int], "species": str, "affinity_type": str, "min_targets": int},
  "ligand_count": int,
  "csv_verification": {
    "rows_matched": int,
    "pairs_verified": int,
    "pairs_failed": int,
    "concordance_rate": float
  },
  "ligands": [sorted by selectivity_window desc, then primary_affinity desc]
}
```

`csv_verification` summarizes cross-validation between API and CSV sources: `rows_matched` is the count of CSV interaction rows matching the query parameters; for each unique (ligand, target) pair in qualifying results, compare the API-derived median pAffinity with the CSV-derived median—`pairs_verified` when within ±0.15, else `pairs_failed`; `concordance_rate` = verified / (verified + failed), defaulting to 1.0 when no comparable pairs exist.

Each ligand object must contain:

- `ligand_id` (int), `ligand_name` (str), `approved` (bool)
- `primary_target_id` (int), `primary_target_name` (str)
- `primary_affinity` (float) — strongest per-target median
- `mean_affinity` (float) — arithmetic mean of per-target medians
- `selectivity_window` (float) — max minus min of per-target affinities
- `ki_selectivity_ratio` (float|null) — 10^(highest) / 10^(second-highest); null when fewer than 2 targets
- `selectivity_entropy` (float) — Shannon entropy of linear-scale affinities (bits)
- `affinities` (dict str→float) — target ID string → median pAffinity
- `original_affinity_nm` (dict str→float) — target ID → molar concentration in nM: 10^(9 − pAffinity)
- `measurement_count` (dict str→int) — target ID → count of independent API measurements contributing to the median
- `pmids` (list[int]) — unique PubMed IDs from interaction records for this ligand across queried targets, sorted ascending
- `interaction_types` (list[str]) — distinct pharmacological action types, sorted alphabetically
- `target_coverage` (float) — fraction of queried targets with data
- `csv_concordance` (float) — fraction of this ligand's per-target values where API and CSV medians agree within ±0.15
- `molecular_properties` — object with keys `molecular_weight` (float|null), `logp` (float|null), `lipinski_violations` (int|null), `hbond_acceptors` (int|null), `hbond_donors` (int|null)

All floats rounded to 4 decimal places. Exit 0 on success including when no ligands qualify (empty list). Non-zero on argument errors or unrecoverable failures.
