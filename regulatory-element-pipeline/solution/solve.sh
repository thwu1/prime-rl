#!/bin/bash

set -euo pipefail

DATA=/app/data
RESULTS=/app/results
TMP=/tmp/solve_tmp
mkdir -p "$RESULTS" "$TMP"

# ==========================================================
# PHASE 1: Audit and fix data quality issues
# Fixes: strand encoding, CpG 1-based coords, chrom names,
#        sort order, genome sizes
# ==========================================================
python3 /solution/fix_data.py

# ==========================================================
# PHASE 2: Run pipeline on corrected data
# ==========================================================

# 1. Strand-aware promoters: 2000 bp upstream of each gene's TSS
bedtools flank -l 2000 -r 0 -s \
    -i "$DATA/genes.bed" \
    -g "$DATA/genome.txt" \
    | sort -k1,1 -k2,2n \
    > "$RESULTS/promoters.bed"

# 2. CpG-overlapping promoter bases, with repeats removed, merged
bedtools intersect \
    -a "$RESULTS/promoters.bed" \
    -b "$DATA/cpg_islands.bed" \
    | bedtools subtract -a stdin -b "$DATA/repeats.bed" \
    | sort -k1,1 -k2,2n \
    | bedtools merge -i - \
    > "$RESULTS/cpg_promoters_norepeats.bed"

# 3. Pairwise Jaccard similarity matrix (5 x 5)
printf "sample\tA\tB\tC\tD\tE\n" > "$RESULTS/jaccard_matrix.tsv"
for s1 in A B C D E; do
    row="$s1"
    for s2 in A B C D E; do
        if [ "$s1" = "$s2" ]; then
            j="1.000000"
        else
            j=$(bedtools jaccard \
                -a "$DATA/tfbs_${s1}.bed" \
                -b "$DATA/tfbs_${s2}.bed" \
                | tail -1 | cut -f3)
        fi
        row="${row}\t${j}"
    done
    printf "%b\n" "$row" >> "$RESULTS/jaccard_matrix.tsv"
done

# 4. Per-gene TFBS score sums from each TF experiment
for tf in A B C D E; do
    bedtools map \
        -a "$RESULTS/promoters.bed" \
        -b "$DATA/tfbs_${tf}.bed" \
        -c 5 -o sum -null 0 \
        | cut -f7 > "$TMP/scores_${tf}.txt"
done

printf "gene\tA\tB\tC\tD\tE\n" > "$RESULTS/tfbs_promoter_scores.tsv"
cut -f4 "$RESULTS/promoters.bed" > "$TMP/gene_names.txt"
paste "$TMP/gene_names.txt" \
      "$TMP/scores_A.txt" "$TMP/scores_B.txt" \
      "$TMP/scores_C.txt" "$TMP/scores_D.txt" \
      "$TMP/scores_E.txt" \
    | sort -k1,1 \
    >> "$RESULTS/tfbs_promoter_scores.tsv"

# 5. Multi-coverage: bases covered by >= 3 of 5 TFBS files
printf "chrom\tbases_covered_by_3plus\n" > "$RESULTS/multi_coverage.tsv"
bedtools multiinter \
    -i "$DATA/tfbs_A.bed" "$DATA/tfbs_B.bed" \
       "$DATA/tfbs_C.bed" "$DATA/tfbs_D.bed" \
       "$DATA/tfbs_E.bed" \
    | awk '$4 >= 3 {print $1"\t"$3-$2}' \
    | sort -k1,1 \
    | bedtools groupby -g 1 -c 2 -o sum \
    >> "$RESULTS/multi_coverage.tsv"

# 6. Regulatory deserts: >= 10 kb regions with zero TFBS from all
cat "$DATA/tfbs_A.bed" "$DATA/tfbs_B.bed" \
    "$DATA/tfbs_C.bed" "$DATA/tfbs_D.bed" \
    "$DATA/tfbs_E.bed" \
    | cut -f1-3 \
    | sort -k1,1 -k2,2n \
    | bedtools merge -i - \
    | bedtools complement -i - -g "$DATA/genome.txt" \
    | awk '$3 - $2 >= 10000' \
    > "$RESULTS/regulatory_deserts.bed"

echo "Pipeline complete. Results in $RESULTS/"
