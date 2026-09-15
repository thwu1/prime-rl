A clinical sequencing laboratory has processed exome data for two families (FAM1, FAM2) under evaluation for Mendelian disease. Each family consists of a trio (father, mother, child). Sample tracking anomalies during library preparation suggest the pedigree on file may contain errors.

Verify sample relationships using the genotype data, identify and correct any pedigree errors, then perform variant prioritization on the affected proband using the corrected family structure.

## Input data

- `/app/cohort.vcf.gz` — bgzipped, tabix-indexed multi-sample VCF (VCFv4.2) with genotypes for 6 individuals (S1–S6) across biallelic SNP sites on chromosomes 1–5. FORMAT fields: GT, DP, GQ, AD.
- `/app/cohort.vcf.gz.tbi` — tabix index
- `/app/pedigree.ped` — tab-separated pedigree (columns: family_id, sample_id, paternal_id, maternal_id, sex, phenotype). One child has phenotype=2 (affected proband).
- `/app/genes.bed` — gene annotations in BED format (0-based start, exclusive end)
- `/app/population_af.tsv` — per-variant population allele frequencies (columns: chrom, pos, ref, alt, af)

## Required outputs

All files in `/app/results/`:

**`kinship.tsv`** — KING-robust pairwise kinship for all 15 sample pairs. Tab-separated with header. Columns: `sample_1`, `sample_2`, `ibs0`, `ibs2`, `shared_hets`, `kinship`. Pairs ordered with sample_1 < sample_2 lexicographically. Kinship rounded to 6 decimal places.

**`swapped_samples.txt`** — The two misassigned sample IDs, space-separated on a single line, alphabetically ordered.

**`corrected.ped`** — Corrected pedigree in the same tab-separated format as the input.

**`denovo.tsv`** — De novo variants in the affected proband under the corrected pedigree. Tab-separated with header. Columns: `chrom`, `pos`, `ref`, `alt`. Population allele frequency threshold: 0.01.

**`compound_hets.tsv`** — Compound heterozygous variant pairs in the proband within gene boundaries from `/app/genes.bed`, with population AF < 0.01. Tab-separated with header. Columns: `gene`, `chrom1`, `pos1`, `chrom2`, `pos2`.