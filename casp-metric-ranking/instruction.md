`/app/data/casp16_prot_domains_scores.csv` contains raw quality assessment scores from the CASP16 protein structure prediction experiment — approximately 50,000 evaluation records with 30+ columns of structural quality metrics. The file is whitespace-delimited with variable-width spacing.

Apply the CASP Prediction Center's z-score-based evaluation methodology to this complete dataset and produce group rankings across five quality metrics (GDT_TS, LDDT, TMscore, CAD_AA, GDT_HA). The evaluation methodology is documented on the Prediction Center website (predictioncenter.org). Evaluate on first-model submissions only, across all target-domain combinations with sufficient data.

Write all outputs to `/app/results/`:

**`casp16_analysis.db`** — SQLite database with:
- Table `first_models` — columns: `target TEXT, group_id TEXT, domain TEXT, GDT_TS REAL, LDDT REAL, TMscore REAL, CAD_AA REAL, GDT_HA REAL`
- Table `group_rankings` — columns: `group_id TEXT, n_domains INTEGER, metric TEXT, sum_zscore REAL, avg_zscore REAL, rank INTEGER`

**`group_rankings.csv`** — One row per group sorted by GDT_TS rank ascending. Columns: `group,n_domains,sum_z_gdt,rank_gdt,sum_z_lddt,rank_lddt,sum_z_tm,rank_tm,sum_z_cad,rank_cad,sum_z_ha,rank_ha`. Z-score sums to 4 decimal places. Group IDs are numeric strings extracted from submission identifiers.

**`metric_correlations.csv`** — Pairwise rank correlation for groups scored on all 5 metrics. Columns: `metric1,metric2,kendall_tau`. 10 rows for ordered pairs from [GDT_TS, LDDT, TMscore, CAD_AA, GDT_HA]. Rounded to 4 decimal places.

**`discriminating_domains.csv`** — Top 10 domains by GDT_TS standard deviation among first models (minimum 10 submissions). Columns: `domain,std_gdt,mean_gdt,median_gdt,n_groups`. Descending by `std_gdt`, floats to 2 decimal places.

**`summary.json`** — `total_first_models` (int), `total_domains` (int), `total_groups` (int), `domains_with_outliers_removed` (int, for GDT_TS among domains with sufficient submissions), `top3_gdt` (list of 3 group ID strings), `top3_lddt` (list of 3 group ID strings).