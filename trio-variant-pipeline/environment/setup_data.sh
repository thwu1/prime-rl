#!/bin/bash
set -e

mkdir -p /app/data

# Compress and index trio VCF
bgzip -c /tmp/trio.vcf > /app/data/trio.vcf.gz
tabix -p vcf /app/data/trio.vcf.gz

# Compress and index population frequency VCF
bgzip -c /tmp/popfreq.vcf > /app/data/popfreq.vcf.gz
tabix -p vcf /app/data/popfreq.vcf.gz

# Compress and index functional regions BED
bgzip -c /tmp/regions.bed > /app/data/regions.bed.gz
tabix -p bed /app/data/regions.bed.gz

# Clean up raw files
rm -f /tmp/trio.vcf /tmp/popfreq.vcf /tmp/regions.bed /tmp/setup_data.sh
