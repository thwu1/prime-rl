#!/bin/bash
set -euo pipefail

# Variant annotation pipeline (corrected)

INPUT_VCF="/app/data/variants.vcf.gz"
REFERENCE="/app/data/reference.fa"
GFF3="/app/data/genes.gff3"
OUTDIR="/app/output"
TMPDIR="/app/tmp"

mkdir -p "$OUTDIR" "$TMPDIR"

echo "Step 1: Normalizing variants with bcftools..."
bcftools norm -m -both -f "$REFERENCE" "$INPUT_VCF" -o "$TMPDIR/normalized.vcf"

echo "Step 2: Creating gene regions BED from GFF3..."
awk -F'\t' '$3=="gene" { name="unknown"; n=split($9,a,";"); for(i=1;i<=n;i++){split(a[i],kv,"="); if(kv[1]=="Name") name=kv[2]}; print $1"\t"($4-1)"\t"$5"\t"name"\t.\t"$7 }' "$GFF3" > "$TMPDIR/genes.bed"

echo "Step 3: Converting normalized VCF to BED format..."
awk '!/^#/ { print $1"\t"($2-1)"\t"($2-1+length($4))"\t"$3"\t"$4"\t"$5 }' \
    "$TMPDIR/normalized.vcf" > "$TMPDIR/variants.bed"

echo "Step 4: Intersecting variants with gene regions..."
bedtools intersect -a "$TMPDIR/variants.bed" -b "$TMPDIR/genes.bed" -loj \
    > "$TMPDIR/intersected.tsv"

echo "Step 5: Classifying variant effects..."
python3 /solution/fixed_classify.py \
    --vcf "$TMPDIR/normalized.vcf" \
    --intersected "$TMPDIR/intersected.tsv" \
    --reference "$REFERENCE" \
    --gff3 "$GFF3" \
    --output "$OUTDIR/variant_effects.tsv"

echo "Pipeline complete. Output: $OUTDIR/variant_effects.tsv"
echo "Annotated $(tail -n +2 "$OUTDIR/variant_effects.tsv" | wc -l) variants."
