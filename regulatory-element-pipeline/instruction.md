A bedtools-based regulatory analysis pipeline was run on the genomic dataset in `/app/data/` and produced incorrect results. The previous analyst's observations are in `/app/NOTES.txt`.

The input files were assembled from heterogeneous upstream sources with different format conventions (UCSC, ENCODE, GFF3 conversions). Multiple files contain data quality defects introduced during format conversion or metadata assembly. The defects cascade through the pipeline in non-obvious ways, corrupting all downstream outputs.

Audit every input file in `/app/data/`, identify and correct all data quality problems, then produce correct analysis results in `/app/results/`.

## Input files

`/app/data/` contains:

- `genome.txt` — chromosome sizes (tab-delimited: chrom, size)
- `genes.bed` — gene annotations (BED6: chrom, start, end, name, score, strand)
- `cpg_islands.bed` — CpG island locations (BED4)
- `repeats.bed` — repetitive elements (BED4)
- `tfbs_A.bed` through `tfbs_E.bed` — TFBS peaks from 5 ChIP-seq experiments (BED5)

## Required outputs

Write all results to `/app/results/`.

1. **`promoters.bed`** — The 2000 bp window immediately upstream of each gene's TSS. For + strand genes the TSS is at the start coordinate; for - strand genes the TSS is at the end coordinate. Clipped to chromosome boundaries. BED6 format preserving each gene's name and strand.

2. **`cpg_promoters_norepeats.bed`** — Promoter base pairs that overlap at least one CpG island AND do not overlap any repetitive element. Merged into non-overlapping intervals (BED3).

3. **`jaccard_matrix.tsv`** — 5×5 pairwise Jaccard similarity between the five TFBS files. Tab-separated with header row `sample\tA\tB\tC\tD\tE`. Each row: sample name then 5 Jaccard values. Diagonal = `1.000000`.

4. **`tfbs_promoter_scores.tsv`** — Per-gene sum of TFBS scores from each experiment overlapping the gene's promoter. Tab-separated, header: `gene\tA\tB\tC\tD\tE`. Body sorted alphabetically by gene name. Use `0` for no overlap.

5. **`multi_coverage.tsv`** — Per-chromosome count of base pairs covered by at least 3 of the 5 TFBS files simultaneously. Tab-separated, header: `chrom\tbases_covered_by_3plus`. Only nonzero chromosomes, sorted by chromosome name.

6. **`regulatory_deserts.bed`** — Genomic regions of at least 10,000 bp with zero TFBS coverage from any of the 5 experiments. BED3 format, sorted by position.