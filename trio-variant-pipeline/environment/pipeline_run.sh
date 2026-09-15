#!/bin/bash
# Trio variant analysis pipeline
set -e

PIPELINE_DIR="$(dirname "$0")"
OUTDIR="/app/results"
mkdir -p "$OUTDIR"


# Annotate trio VCF with population frequencies and functional scores
vcfanno "$PIPELINE_DIR/vcfanno.toml" /app/data/trio.vcf.gz 2>/dev/null | bgzip > /app/annotated.vcf.gz
tabix -p vcf /app/annotated.vcf.gz

# De novo variant filtering
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped "$PIPELINE_DIR/trio.ped" \
    --pass-only \
    --info "(!('pop_af' in INFO) || INFO.pop_af < 0.05)" \
    --trio "denovo:kid.het && mom.hom_ref && dad.hom_ref && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10" \
    -o /app/denovo.bcf 2>/dev/null

# Autosomal recessive variant filtering
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped "$PIPELINE_DIR/trio.ped" \
    --pass-only \
    --trio "recessive:kid.hom_alt && mom.het && dad.het && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10" \
    -o /app/recessive.bcf 2>/dev/null

# Compound heterozygote candidate filtering
slivar expr \
    --vcf /app/annotated.vcf.gz \
    --ped "$PIPELINE_DIR/trio.ped" \
    --pass-only \
    --info "(!('pop_af' in INFO) || INFO.pop_af < 0.05)" \
    --trio "comphet_side:kid.het && ((mom.het && dad.hom_ref) || (dad.het && mom.hom_ref)) && kid.GQ >= 20 && mom.GQ >= 20 && dad.GQ >= 20 && kid.DP >= 10 && mom.DP >= 10 && dad.DP >= 10" \
    -o /app/comphet_candidates.bcf 2>/dev/null

# Compound het pair detection
slivar compound-hets \
    --vcf /app/comphet_candidates.bcf \
    --ped "$PIPELINE_DIR/trio.ped" \
    -o /app/compound_hets.vcf 2>/dev/null

# Write variant counts
bcftools view -H /app/denovo.bcf | wc -l | tr -d ' ' > "$OUTDIR/denovo_count.txt"
bcftools view -H /app/recessive.bcf | wc -l | tr -d ' ' > "$OUTDIR/recessive_count.txt"
bcftools query -f '%INFO/BCSQ\n' /app/compound_hets.vcf 2>/dev/null | \
    awk -F'|' '{print $2}' | sort -u | grep -v '^\s*$' > "$OUTDIR/compound_het_genes.txt"

# Rank de novo candidates and select top variant
python3 -c "
import subprocess

SEVERITY = {
    'stop_gained': 100, 'frameshift': 95, 'splice_donor': 90, 'splice_acceptor': 90,
    'missense': 50, 'synonymous': 10,
}

result = subprocess.run(
    ['bcftools', 'query', '-f', '%CHROM:%POS:%REF:%ALT\t%INFO/BCSQ\t%INFO/func_score\n', '/app/denovo.bcf'],
    capture_output=True, text=True,
)

best_vid, best_fscore, best_sev = None, -1.0, -1
for line in result.stdout.strip().split('\n'):
    if not line.strip():
        continue
    parts = line.split('\t')
    vid = parts[0]
    bcsq = parts[1] if len(parts) > 1 else ''
    fs = float(parts[2]) if len(parts) > 2 and parts[2] != '.' else 0.0
    csq = bcsq.split('|')[0] if bcsq and bcsq != '.' else ''
    sev = SEVERITY.get(csq, 0)
    if (fs > best_fscore) or (fs == best_fscore and sev > best_sev):
        best_vid, best_fscore, best_sev = vid, fs, sev

with open('$OUTDIR/top_candidate.txt', 'w') as f:
    f.write(best_vid + '\n')
"
