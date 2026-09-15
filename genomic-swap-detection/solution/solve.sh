#!/bin/bash

set -e
cd /app
mkdir -p results /tmp/work

# Phase 1: Extract data from compressed VCF using bcftools
bcftools query -l cohort.vcf.gz > /tmp/work/samples.txt
bcftools query -f '%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n' cohort.vcf.gz > /tmp/work/gt_matrix.tsv

# Phase 2: Kinship analysis, swap detection, pedigree correction, de novo calling
python3 /solution/analyze.py

# Phase 3: Map proband rare het variants to gene regions using bedtools
bedtools intersect \
    -a /tmp/work/proband_rare_hets.bed \
    -b /app/genes.bed \
    -wa -wb \
    > /tmp/work/gene_mapped.tsv

# Phase 4: Compile compound heterozygous pairs from bedtools output
python3 /solution/find_compound_hets.py
