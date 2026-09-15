#!/bin/bash

set -euo pipefail

cd /app
mkdir -p results work

###############################################################################
# Data quality fixes discovered through exploration:
#
# 1. variants.bed uses bare chromosome names ("1","2","3") while all other
#    files use the "chr" prefix. Must normalize.
# 2. enhancers.gff is in GFF3 format (1-based, inclusive end) while BED uses
#    0-based, half-open coordinates. Column 4 is the 1-based start.
# 3. cpg_islands.bed is not sorted — bedtools requires sorted input for many
#    operations.
# 4. variants.bed contains exact duplicate rows that must be removed.
# 5. promoters.bed has overlapping entries that must be merged after combining
#    with enhancers to avoid double-counting.
###############################################################################

# Fix 1 & 4: Normalize variant chr names and deduplicate
awk 'BEGIN{OFS="\t"}{$1="chr"$1; print}' data/variants.bed \
    | sort -k1,1 -k2,2n \
    | uniq \
    > work/variants_fixed.bed

# Fix 2: Convert enhancers from GFF3 (1-based start) to BED3 (0-based start)
grep -v '^#' data/enhancers.gff \
    | awk 'BEGIN{OFS="\t"}{print $1, $4-1, $5}' \
    | sort -k1,1 -k2,2n \
    > work/enhancers.bed

# Fix 3: Sort CpG islands
sort -k1,1 -k2,2n data/cpg_islands.bed > work/cpg_sorted.bed

# Fix 5: Combine promoters + enhancers, sort, and merge overlapping regions
cut -f1-3 data/promoters.bed > work/promoters_bed3.bed
cat work/promoters_bed3.bed work/enhancers.bed \
    | sort -k1,1 -k2,2n \
    | bedtools merge -i - \
    > work/regulatory_all.bed

# Step A: Intersect regulatory regions with CpG islands
bedtools intersect \
    -a work/regulatory_all.bed \
    -b work/cpg_sorted.bed \
    > work/reg_cpg.bed

# Step B: Subtract repeat elements
bedtools subtract \
    -a work/reg_cpg.bed \
    -b data/repeats.bed \
    > work/reg_cpg_norep.bed

# Step C: Identify expressed genes (FPKM >= 10) and create 2kb neighborhoods
awk -F'\t' 'NR>1 && $2+0>=10{print $1}' data/expression.tsv > work/expressed_names.txt

awk 'NR==FNR{g[$1]; next} $4 in g' work/expressed_names.txt data/genes.bed \
    | sort -k1,1 -k2,2n \
    > work/expressed_genes.bed

bedtools slop \
    -i work/expressed_genes.bed \
    -g data/genome.txt \
    -b 2000 \
    | sort -k1,1 -k2,2n \
    | bedtools merge -i - \
    > work/expressed_neighborhoods.bed

# Step D: Active regions = regulatory ∩ CpG − repeats, filtered to expressed neighborhoods
bedtools intersect \
    -a work/reg_cpg_norep.bed \
    -b work/expressed_neighborhoods.bed \
    | sort -k1,1 -k2,2n \
    | bedtools merge -i - \
    > results/active_regions.bed

# Step E: Find regulatory variants (variants overlapping active regions)
bedtools intersect \
    -a work/variants_fixed.bed \
    -b results/active_regions.bed \
    -u \
    | sort -k1,1 -k2,2n \
    > results/regulatory_variants.bed

# Step F: Compute summary statistics
reg_var_count=$(wc -l < results/regulatory_variants.bed)
total_var_count=$(wc -l < work/variants_fixed.bed)
active_count=$(wc -l < results/active_regions.bed)
active_bp=$(awk '{s+=$3-$2}END{print s+0}' results/active_regions.bed)
fraction=$(python3 -c "print('{:.4f}'.format($reg_var_count / $total_var_count))")

echo "regulatory_variant_count=${reg_var_count}" > results/summary.txt
echo "total_variant_count=${total_var_count}" >> results/summary.txt
echo "active_region_count=${active_count}" >> results/summary.txt
echo "active_region_total_bp=${active_bp}" >> results/summary.txt
echo "fraction_regulatory=${fraction}" >> results/summary.txt

echo "=== Pipeline complete ==="
cat results/summary.txt
