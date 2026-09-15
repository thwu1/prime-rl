#!/bin/bash

set -e

# Create correct PED file for the trio
printf "#family_id\tsample_id\tpaternal_id\tmaternal_id\tsex\tphenotype\n" > /app/trio.ped
printf "FAM001\tHG002\tHG003\tHG004\t1\t2\n" >> /app/trio.ped
printf "FAM001\tHG003\t0\t0\t1\t1\n" >> /app/trio.ped
printf "FAM001\tHG004\t0\t0\t2\t1\n" >> /app/trio.ped

# Create corrected vcfanno TOML configuration
# FIX: Annotation output field named "pop_af" to match slivar filter references
# (broken pipeline named it "AF", causing pop_af to never exist in INFO,
#  which made the short-circuit evaluation silently pass all frequency checks)
cat > /app/vcfanno.toml << 'TOML_EOF'
[[annotation]]
file="/app/data/popfreq.vcf.gz"
fields=["AF"]
ops=["self"]
names=["pop_af"]

[[annotation]]
file="/app/data/regions.bed.gz"
columns=[4]
ops=["mean"]
names=["func_score"]
TOML_EOF

# Step 1: Annotate trio VCF with population frequencies and functional scores
vcfanno /app/vcfanno.toml /app/data/trio.vcf.gz 2>/dev/null | bgzip > /app/annotated.vcf.gz
tabix -p vcf /app/annotated.vcf.gz

# Step 2: Filter de novo variants
# FIX: AF threshold set to 0.01 (clinical standard for rare Mendelian disease)
# FIX: Added parental alt depth evidence check to exclude parental mosaicism
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped /app/trio.ped \
    --pass-only \
    --info "(!('pop_af' in INFO) || INFO.pop_af < 0.01)" \
    --trio "denovo:kid.het && mom.hom_ref && dad.hom_ref && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10 && (mom.AD[1] + dad.AD[1]) < 2" \
    -o /app/denovo.bcf 2>/dev/null

# Step 3: Filter autosomal recessive variants
# FIX: Added --info AF filter (all inheritance models require frequency filtering)
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped /app/trio.ped \
    --pass-only \
    --info "(!('pop_af' in INFO) || INFO.pop_af < 0.01)" \
    --trio "recessive:kid.hom_alt && mom.het && dad.het && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10" \
    -o /app/recessive.bcf 2>/dev/null

# Step 4: Compound het candidates
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped /app/trio.ped \
    --pass-only \
    --info "(!('pop_af' in INFO) || INFO.pop_af < 0.01)" \
    --trio "comphet_side:kid.het && ((mom.het && dad.hom_ref) || (dad.het && mom.hom_ref)) && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10" \
    -o /app/comphet_candidates.bcf 2>/dev/null

# Step 5: Find compound het pairs
slivar compound-hets \
    --vcf /app/comphet_candidates.bcf \
    --ped /app/trio.ped \
    -o /app/compound_hets.vcf 2>/dev/null

# Step 6: Write results
mkdir -p /app/results
bcftools view -H /app/denovo.bcf | wc -l | tr -d ' ' > /app/results/denovo_count.txt
bcftools view -H /app/recessive.bcf | wc -l | tr -d ' ' > /app/results/recessive_count.txt
bcftools query -f '%INFO/BCSQ\n' /app/compound_hets.vcf 2>/dev/null | \
    awk -F'|' '{print $2}' | sort -u | grep -v '^\s*$' > /app/results/compound_het_genes.txt

# Step 7: Identify top candidate with correct clinical ranking
# FIX: Ranking now uses consequence severity first (ACMG LoF > missense > synonymous),
# with functional score as tiebreaker only within same severity class
python3 /solution/analyze.py
