#!/usr/bin/env python3
"""Generate synthetic genomic data for the benchmark pipeline audit task.

Creates a deterministic reference FASTA and VCF with variants at known positions.
VCF is bgzipped and tabix-indexed. Run during Docker build.
"""

import random
import os
import subprocess

CHROM = "chr_test"
REF_LENGTH = 500000
SEED = 42
LINE_WIDTH = 80

random.seed(SEED)
ref_seq = ''.join(random.choice('ACGT') for _ in range(REF_LENGTH))

# Write reference FASTA
with open('/app/reference.fa', 'w') as f:
    f.write(f'>{CHROM}\n')
    for i in range(0, REF_LENGTH, LINE_WIDTH):
        f.write(ref_seq[i:i + LINE_WIDTH] + '\n')

# Write FASTA index (.fai)
header_len = len(f'>{CHROM}\n')
with open('/app/reference.fa.fai', 'w') as f:
    f.write(f'{CHROM}\t{REF_LENGTH}\t{header_len}\t{LINE_WIDTH}\t{LINE_WIDTH + 1}\n')


def alt_base(ref_base):
    """Return the first base in ACGT that differs from ref_base."""
    for b in 'ACGT':
        if b != ref_base:
            return b


# Variant specifications: (pos_1based, var_type, genotype, qual, dp)
# Some genotypes use phased notation (| separator)
variant_specs = [
    (1000, 'snp', '0/1', 50, 30),
    (5000, 'snp', '1/1', 60, 40),
    (12000, 'snp', '0/1', 50, 30),
    (15000, 'snp', '0/1', 45, 25),
    (27000, 'snp', '0|1', 45, 25),
    (35000, 'snp', '0/1', 55, 35),
    (40000, 'ins_AGG', '0/1', 50, 30),
    (51000, 'snp', '0/1', 60, 40),
    (60000, 'del2', '1/1', 60, 40),
    (75500, 'snp', '0/1', 52, 32),
    (80000, 'snp', '1|0', 48, 28),
    (90000, 'snp', '0/1', 52, 32),
    (100500, 'snp', '0/1', 55, 35),
    (110000, 'snp', '0/1', 44, 24),
    (122000, 'snp', '0/1', 44, 24),
    (130000, 'snp', '1|1', 60, 40),
    (141000, 'snp', '0/1', 40, 20),
    (143500, 'snp', '0/1', 48, 28),
    (150000, 'snp', '0|1', 50, 30),
    (160000, 'del1', '0/1', 46, 26),
    (170000, 'snp', '0/1', 58, 38),
    (185000, 'snp', '0/1', 46, 26),
    (197000, 'snp', '0/1', 42, 22),
    (210000, 'snp', '1/1', 60, 40),
    (220000, 'snp', '0/1', 54, 34),
    (240000, 'snp', '0/1', 50, 30),
    (252000, 'snp', '0/1', 58, 38),
    (260000, 'snp', '1|0', 45, 25),
    (270000, 'snp', '0/1', 55, 35),
    (280000, 'del2', '1/1', 60, 40),
    (295000, 'snp', '0/1', 48, 28),
    (300000, 'snp', '0/1', 52, 32),
    (310500, 'snp', '0/1', 54, 34),
    (320000, 'snp', '0/1', 44, 24),
    (340000, 'snp', '0/1', 50, 30),
    (370000, 'snp', '1|1', 60, 40),
    (381000, 'snp', '0/1', 50, 30),
    (390000, 'snp', '0|1', 46, 26),
    (410000, 'snp', '0/1', 58, 38),
    (420000, 'ins_TCG', '0/1', 42, 22),
    (430000, 'del2', '0/1', 54, 34),
    (465000, 'snp', '0/1', 50, 30),
    (471000, 'snp', '0/1', 42, 22),
    (480000, 'snp', '1|0', 45, 25),
    (495000, 'snp', '0/1', 55, 35),
]

with open('/app/calls.vcf', 'w') as f:
    f.write('##fileformat=VCFv4.2\n')
    f.write('##FILTER=<ID=PASS,Description="All filters passed">\n')
    f.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
    f.write('##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype Quality">\n')
    f.write('##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read Depth">\n')
    f.write(f'##contig=<ID={CHROM},length={REF_LENGTH}>\n')
    f.write('#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n')

    for pos, vtype, gt, qual, dp in variant_specs:
        idx = pos - 1  # 0-based index
        ref_base = ref_seq[idx]

        if vtype == 'snp':
            ref = ref_base
            alt = alt_base(ref_base)
        elif vtype == 'ins_AGG':
            ref = ref_base
            alt = ref_base + 'AGG'
        elif vtype == 'ins_TCG':
            ref = ref_base
            alt = ref_base + 'TCG'
        elif vtype == 'del1':
            ref = ref_seq[idx:idx + 2]
            alt = ref_base
        elif vtype == 'del2':
            ref = ref_seq[idx:idx + 3]
            alt = ref_base

        f.write(f'{CHROM}\t{pos}\t.\t{ref}\t{alt}\t{qual}\tPASS\t.\tGT:GQ:DP\t{gt}:{qual}:{dp}\n')

# Bgzip and tabix-index the VCF
subprocess.run(["bgzip", "/app/calls.vcf"], check=True)
subprocess.run(["tabix", "-p", "vcf", "/app/calls.vcf.gz"], check=True)

print(f"Generated reference: {REF_LENGTH} bp")
print(f"Generated VCF: {len(variant_specs)} variants (bgzipped + indexed)")
