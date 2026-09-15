#!/bin/bash


# Cross-reference parsed half-lives from results.json against curated_reference.tsv
# Uses jq for JSON extraction and awk for TSV join and discrepancy computation

set -e
cd /app

mkdir -p /app/output

# Extract parsed half-lives from results.json into a temp TSV
jq -r '.drug_extractions[] | [.drugbank_id, (.parsed_half_life_hours | tostring)] | @tsv' \
    /app/output/results.json > /tmp/parsed_hl.tsv

# Write header
printf "drugbank_id\tparsed_hours\tcurated_hours\tpct_discrepancy\tstatus\n" \
    > /app/output/reconciliation.tsv

# Join parsed values with curated reference, compute discrepancy
awk -F'\t' '
NR==FNR && FNR>1 {
    curated[$1] = $2
    next
}
NR!=FNR {
    did = $1
    parsed = $2 + 0
    if (did in curated) {
        cur = curated[did] + 0
        if (cur > 0) {
            disc = ((parsed - cur) > 0 ? (parsed - cur) : (cur - parsed)) / cur * 100
        } else {
            disc = 0
        }
        status = (disc <= 5) ? "MATCH" : "MISMATCH"
        printf "%s\t%.4f\t%.4f\t%.2f\t%s\n", did, parsed, cur, disc, status
    }
}
' /app/curated_reference.tsv /tmp/parsed_hl.tsv >> /app/output/reconciliation.tsv

rm -f /tmp/parsed_hl.tsv
echo "Reconciliation complete: $(tail -n +2 /app/output/reconciliation.tsv | wc -l) drugs compared"
