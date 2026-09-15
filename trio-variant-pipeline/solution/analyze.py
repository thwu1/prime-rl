#!/usr/bin/env python3
"""Identify the top candidate causal variant from de novo filtering results.

Correct ranking logic (ACMG/AMP-aligned):
  1. Consequence severity (stop_gained/frameshift/splice > missense > synonymous)
  2. Functional impact score as tiebreaker within same severity class
"""

import subprocess

CONSEQUENCE_SEVERITY = {
    "stop_gained": 100,
    "frameshift": 95,
    "splice_donor": 90,
    "splice_acceptor": 90,
    "missense": 50,
    "inframe_deletion": 40,
    "inframe_insertion": 40,
    "synonymous": 10,
    "intron": 5,
    "intergenic": 1,
    "3_prime_UTR": 5,
    "5_prime_UTR": 5,
}

result = subprocess.run(
    ["bcftools", "query", "-f", "%CHROM:%POS:%REF:%ALT\t%INFO/BCSQ\t%INFO/func_score\n", "/app/denovo.bcf"],
    capture_output=True,
    text=True,
)

best_variant = None
best_severity = -1
best_func_score = -1.0

for line in result.stdout.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t")
    variant_id = parts[0]

    bcsq = parts[1] if len(parts) > 1 else ""
    func_score_str = parts[2] if len(parts) > 2 else "0"

    consequence = bcsq.split("|")[0] if bcsq and bcsq != "." else ""
    severity = CONSEQUENCE_SEVERITY.get(consequence, 0)

    try:
        func_score = float(func_score_str) if func_score_str != "." else 0.0
    except ValueError:
        func_score = 0.0

    if (severity > best_severity) or (severity == best_severity and func_score > best_func_score):
        best_severity = severity
        best_func_score = func_score
        best_variant = variant_id

with open("/app/results/top_candidate.txt", "w") as f:
    f.write(best_variant + "\n")
