#!/bin/bash

set -e
cd /app
mkdir -p /app/output /app/tmp

# Decompress the bgzipped VCF for processing
zcat /app/data/variants.vcf.gz > /app/tmp/variants.vcf

# Run standalone variant annotator that handles left-normalization,
# gene overlap detection, splice site classification, reverse strand
# complementation, and effect prediction internally — bypassing
# the buggy pipeline entirely.
python3 /solution/annotate_variants.py \
    --reference /app/data/reference.fa \
    --gff3 /app/data/genes.gff3 \
    --vcf /app/tmp/variants.vcf \
    --output /app/output/variant_effects.tsv
