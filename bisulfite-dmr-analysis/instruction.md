Bisulfite sequencing count data is at `/opt/data/bisulfite_counts.tsv` covering 500 CpG sites across 16 samples (8 case, 8 control). Each row has `cpg_id`, `chr`, `position`, then paired columns per sample: `{sample}_meth` (methylated read count) and `{sample}_total` (total read count).

Sample metadata is at `/opt/data/sample_metadata.tsv` (columns: `sample_id`, `condition`, `batch`, `sex`).

Gene annotations are at `/opt/data/gene_annotations.tsv` (columns: `gene_id`, `chr`, `tss`, `strand`).

Analyze the data for differential methylation between case and control conditions and produce three output files in `/app/`:

**`/app/cpg_results.tsv`** — Per-CpG differential methylation results. Only include CpGs with adequate sequencing depth across all samples. Columns: `cpg_id`, `chr`, `position`, `mean_case_beta`, `mean_ctrl_beta`, `delta_beta`, `pvalue`, `padj`, `significant` (TRUE/FALSE, uppercase).

**`/app/dmr_results.tsv`** — Differentially methylated regions identified from significant CpGs. Columns: `dmr_id`, `chr`, `start`, `end`, `n_cpgs`, `mean_delta_beta`, `direction` (hyper/hypo), `nearest_gene`, `distance_to_tss`.

**`/app/qc_report.tsv`** — Quality control summary with columns `metric` and `value`. Required metrics: `total_cpgs`, `filtered_cpgs`, `tested_cpgs`, `significant_cpgs`, `n_dmrs`, `batch_correction_method`.