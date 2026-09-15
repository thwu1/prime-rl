Analyze whole-genome sequencing read depth data from a multi-sample tumor cohort to characterize somatic copy number alterations, estimate per-sample tumor purity, and identify recurrently affected cancer genes. The data at `/app/data/` contains:

- `read_depths.csv` — Read depth counts across 500 genomic windows (5 chromosomes x 100 windows at 1 Mb resolution) for 8 samples (6 tumor: T1-T6, 2 normal: N1, N2), with per-window `gc_content`.
- `sample_metadata.csv` — Sample identifiers and types. Tumor purity varies across samples and is not provided.
- `gene_annotations.bed` — BED-format cancer gene annotations (7 columns: chrom, start, end, gene_name, score, strand, role).
- `genome.chrom.sizes` — Chromosome sizes.

`bedtools`, `bgzip`, and `tabix` are installed.

## Required outputs in `/app/output/`

`cnv_segments.csv` — Per-sample non-neutral CNV segments. Columns: `sample`, `chromosome`, `start`, `end`, `log2_ratio`, `copy_number`. Copy numbers: integers in [0, 10]. All segments: start < end.

`purity_estimates.csv` — Estimated tumor purity per tumor sample. Columns: `sample`, `purity`. Values in (0, 1].

`per_sample/{sample}.bed` — One coordinate-sorted BED file per tumor sample (T1-T6) with CNV calls. Tab-delimited, >= 5 columns (chrom, start, end, name, score).

`all_cnv_segments.bed.gz` — bgzip-compressed combined BED of all segments, genome-coordinate-sorted, with tabix index at `all_cnv_segments.bed.gz.tbi`.

`recurrent_regions.csv` — Regions altered in >= 2 tumor samples. Columns: `chromosome`, `start`, `end`, `n_samples`, `type` (gain or loss). At least 2 regions required.

`affected_genes.csv` — Cancer genes overlapping recurrently altered regions. Columns: `gene`, `chromosome`, `region_type`, `n_samples`. All entries: n_samples >= 2. At least 3 genes required.

## Validation criteria

The data contains multiple embedded CNV events across tumor samples at varying purity levels. Detection sensitivity must reach >= 70% (loss: mean copy number < 2 in the event region; gain: > 2).

A multi-sample deletion region exists on chr1 (~20-35 Mb) and a multi-sample amplification region on chr3 (~45-70 Mb), each present in >= 3 samples.

Affected genes must include relevant tumor suppressors in deletion regions and oncogenes in amplification regions from the annotation.

Purity estimates must be within 0.15 of true values for >= 4 of 6 tumor samples.