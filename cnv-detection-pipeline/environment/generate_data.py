#!/usr/bin/env python3
"""Generate synthetic WGS read depth data for CNV detection task."""
import random
import math
import csv
import os

random.seed(42)

N_CHR = 5
WIN_PER_CHR = 100
WIN_SIZE = 1_000_000
BASE_DEPTH = 100

TUMOR_SAMPLES = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6']
NORMAL_SAMPLES = ['N1', 'N2']
ALL_SAMPLES = NORMAL_SAMPLES + TUMOR_SAMPLES

PURITIES = {'T1': 0.80, 'T2': 0.60, 'T3': 0.90, 'T4': 0.70, 'T5': 0.50, 'T6': 0.75}

CNV_EVENTS = [
    ('T1', 0, 20, 35, 1),
    ('T1', 2, 45, 70, 3),
    ('T2', 0, 18, 38, 1),
    ('T2', 2, 50, 68, 3),
    ('T3', 1, 75, 95, 4),
    ('T4', 2, 42, 72, 3),
    ('T4', 4, 10, 30, 1),
    ('T5', 0, 22, 33, 1),
    ('T6', 2, 48, 65, 3),
    ('T6', 3, 25, 50, 0),
]


def poisson_approx(lam):
    val = random.gauss(lam, math.sqrt(max(lam, 1)))
    return max(0, int(round(val)))


def gc_bias(gc):
    return 1.0 + 0.5 * (gc - 0.5) ** 2 - 0.3 * (gc - 0.5)


n_windows = N_CHR * WIN_PER_CHR

gc_content = []
for c in range(N_CHR):
    for w in range(WIN_PER_CHR):
        base = 0.40 + 0.10 * math.sin(4 * math.pi * w / WIN_PER_CHR)
        gc = base + random.gauss(0, 0.02)
        gc = max(0.20, min(0.80, gc))
        gc_content.append(gc)

gc_factors = [gc_bias(g) for g in gc_content]

os.makedirs('/app/data', exist_ok=True)

depth_data = {}
for sample in ALL_SAMPLES:
    cn = [2.0] * n_windows
    if sample in TUMOR_SAMPLES:
        p = PURITIES[sample]
        for ev_sample, chr_idx, sw, ew, ev_cn in CNV_EVENTS:
            if ev_sample == sample:
                off = chr_idx * WIN_PER_CHR
                for i in range(sw, ew):
                    cn[off + i] = p * ev_cn + (1 - p) * 2

    lib_factor = random.uniform(0.80, 1.20)
    depths = []
    for i in range(n_windows):
        expected = BASE_DEPTH * (cn[i] / 2.0) * gc_factors[i] * lib_factor
        depths.append(poisson_approx(expected))
    depth_data[sample] = depths

with open('/app/data/read_depths.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['chromosome', 'start', 'end', 'gc_content'] + ALL_SAMPLES)
    for i in range(n_windows):
        c = i // WIN_PER_CHR
        wi = i % WIN_PER_CHR
        row = [f'chr{c + 1}', wi * WIN_SIZE, (wi + 1) * WIN_SIZE, f'{gc_content[i]:.4f}']
        row += [depth_data[s][i] for s in ALL_SAMPLES]
        writer.writerow(row)

with open('/app/data/sample_metadata.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['sample', 'type'])
    for s in NORMAL_SAMPLES:
        writer.writerow([s, 'normal'])
    for s in TUMOR_SAMPLES:
        writer.writerow([s, 'tumor'])

gene_data = [
    ('BRCA1', 0, 5, 'tumor_suppressor'),
    ('TP53', 0, 15, 'tumor_suppressor'),
    ('RB1', 0, 25, 'tumor_suppressor'),
    ('CDKN2A', 0, 30, 'tumor_suppressor'),
    ('APC', 0, 50, 'tumor_suppressor'),
    ('PTEN', 0, 75, 'tumor_suppressor'),
    ('MYC', 1, 10, 'oncogene'),
    ('KRAS', 1, 30, 'oncogene'),
    ('EGFR', 1, 55, 'oncogene'),
    ('ERBB2', 1, 80, 'oncogene'),
    ('CDK4', 1, 85, 'oncogene'),
    ('MDM2', 1, 90, 'oncogene'),
    ('PIK3CA', 2, 15, 'oncogene'),
    ('BRAF', 2, 35, 'oncogene'),
    ('CCND1', 2, 48, 'oncogene'),
    ('FGFR1', 2, 55, 'oncogene'),
    ('MYB', 2, 58, 'oncogene'),
    ('FGF19', 2, 62, 'oncogene'),
    ('CCNE1', 2, 65, 'oncogene'),
    ('MET', 2, 70, 'oncogene'),
    ('ALK', 3, 10, 'oncogene'),
    ('SMAD4', 3, 30, 'tumor_suppressor'),
    ('ARID1A', 3, 35, 'tumor_suppressor'),
    ('CDKN1B', 3, 40, 'tumor_suppressor'),
    ('NF1', 3, 60, 'tumor_suppressor'),
    ('NOTCH1', 3, 80, 'oncogene'),
    ('VHL', 4, 5, 'tumor_suppressor'),
    ('SETD2', 4, 15, 'tumor_suppressor'),
    ('BAP1', 4, 20, 'tumor_suppressor'),
    ('PBRM1', 4, 25, 'tumor_suppressor'),
    ('AKT1', 4, 50, 'oncogene'),
    ('TERT', 4, 75, 'oncogene'),
]

# Write gene annotations as BED format (chrom, start, end, gene_name, score, strand, role)
with open('/app/data/gene_annotations.bed', 'w') as f:
    for gene, chr_idx, win_idx, role in gene_data:
        chrom = f'chr{chr_idx + 1}'
        start = win_idx * WIN_SIZE
        end = win_idx * WIN_SIZE + 500000
        f.write(f'{chrom}\t{start}\t{end}\t{gene}\t0\t+\t{role}\n')

# Write genome chromosome sizes file (required by bedtools)
with open('/app/data/genome.chrom.sizes', 'w') as f:
    for c in range(1, N_CHR + 1):
        f.write(f'chr{c}\t{WIN_PER_CHR * WIN_SIZE}\n')

print("Data generated successfully.")
