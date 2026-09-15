#!/usr/bin/env python3
"""
Generate synthetic genomic data for regulatory variant analysis task.
Creates files with deliberate quality issues that must be identified and fixed.

Issues planted:
1. variants.bed uses bare chromosome names ("1","2","3") instead of "chr1","chr2","chr3"
2. enhancers.gff uses GFF3 format (1-based coordinates) instead of BED (0-based)
3. cpg_islands.bed is deliberately unsorted
4. variants.bed contains duplicate entries
5. promoters.bed has overlapping entries that need merging
"""
import os
import random

random.seed(42)

os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/results', exist_ok=True)

# === Genome sizes ===
with open('/app/data/genome.txt', 'w') as f:
    f.write("chr1\t100000\n")
    f.write("chr2\t80000\n")
    f.write("chr3\t60000\n")

# === Genes (BED6, chr prefix, sorted) ===
genes = [
    ("chr1", 5000, 8000, "GENE_A", 0, "+"),
    ("chr1", 12000, 15000, "GENE_B", 0, "-"),
    ("chr1", 22000, 28000, "GENE_C", 0, "+"),
    ("chr1", 35000, 40000, "GENE_D", 0, "-"),
    ("chr1", 50000, 55000, "GENE_E", 0, "+"),
    ("chr1", 65000, 70000, "GENE_F", 0, "-"),
    ("chr1", 80000, 85000, "GENE_G", 0, "+"),
    ("chr1", 92000, 96000, "GENE_H", 0, "+"),
    ("chr2", 5000, 10000, "GENE_I", 0, "-"),
    ("chr2", 18000, 22000, "GENE_J", 0, "+"),
    ("chr2", 30000, 35000, "GENE_K", 0, "-"),
    ("chr2", 45000, 50000, "GENE_L", 0, "+"),
    ("chr2", 60000, 65000, "GENE_M", 0, "-"),
    ("chr2", 72000, 76000, "GENE_N", 0, "+"),
    ("chr3", 5000, 9000, "GENE_O", 0, "-"),
    ("chr3", 15000, 20000, "GENE_P", 0, "+"),
    ("chr3", 28000, 33000, "GENE_Q", 0, "-"),
    ("chr3", 42000, 47000, "GENE_R", 0, "+"),
    ("chr3", 52000, 56000, "GENE_S", 0, "-"),
]
with open('/app/data/genes.bed', 'w') as f:
    for chrom, start, end, name, score, strand in genes:
        f.write(f"{chrom}\t{start}\t{end}\t{name}\t{score}\t{strand}\n")

# === Expression data (TSV with header) ===
expression = [
    ("GENE_A", 25.0), ("GENE_B", 5.0), ("GENE_C", 50.0), ("GENE_D", 12.0),
    ("GENE_E", 0.5), ("GENE_F", 30.0), ("GENE_G", 8.0), ("GENE_H", 45.0),
    ("GENE_I", 15.0), ("GENE_J", 3.0), ("GENE_K", 60.0), ("GENE_L", 20.0),
    ("GENE_M", 7.0), ("GENE_N", 35.0), ("GENE_O", 40.0), ("GENE_P", 2.0),
    ("GENE_Q", 55.0), ("GENE_R", 11.0), ("GENE_S", 9.0),
]
with open('/app/data/expression.tsv', 'w') as f:
    f.write("gene_name\tFPKM\n")
    for name, fpkm in expression:
        f.write(f"{name}\t{fpkm}\n")

# === Promoters (BED4, chr prefix, sorted, WITH overlapping entries) ===
promoters = [
    ("chr1", 3000, 5000, "prom_GENE_A"),
    ("chr1", 4500, 5500, "prom_GENE_A_alt"),
    ("chr1", 15000, 17000, "prom_GENE_B"),
    ("chr1", 20000, 22000, "prom_GENE_C"),
    ("chr1", 40000, 42000, "prom_GENE_D"),
    ("chr1", 48000, 50000, "prom_GENE_E"),
    ("chr1", 70000, 72000, "prom_GENE_F"),
    ("chr1", 78000, 80000, "prom_GENE_G"),
    ("chr1", 90000, 92000, "prom_GENE_H"),
    ("chr2", 10000, 12000, "prom_GENE_I"),
    ("chr2", 11000, 12500, "prom_GENE_I_alt"),
    ("chr2", 16000, 18000, "prom_GENE_J"),
    ("chr2", 35000, 37000, "prom_GENE_K"),
    ("chr2", 43000, 45000, "prom_GENE_L"),
    ("chr2", 65000, 67000, "prom_GENE_M"),
    ("chr2", 70000, 72000, "prom_GENE_N"),
    ("chr3", 9000, 11000, "prom_GENE_O"),
    ("chr3", 13000, 15000, "prom_GENE_P"),
    ("chr3", 33000, 35000, "prom_GENE_Q"),
    ("chr3", 40000, 42000, "prom_GENE_R"),
    ("chr3", 56000, 58000, "prom_GENE_S"),
]
with open('/app/data/promoters.bed', 'w') as f:
    for chrom, start, end, name in promoters:
        f.write(f"{chrom}\t{start}\t{end}\t{name}\n")

# === Enhancers (GFF3 format — 1-based, inclusive end coordinates) ===
enhancers_bed = [
    ("chr1", 3500, 4200),
    ("chr1", 10000, 11500),
    ("chr1", 24000, 25500),
    ("chr1", 36000, 37000),
    ("chr1", 64000, 65500),
    ("chr1", 90000, 91500),
    ("chr2", 3000, 4500),
    ("chr2", 17000, 18500),
    ("chr2", 44000, 45500),
    ("chr2", 71000, 72500),
    ("chr3", 3500, 5000),
    ("chr3", 27000, 28500),
    ("chr3", 41000, 42500),
    ("chr3", 51000, 52500),
]
with open('/app/data/enhancers.gff', 'w') as f:
    f.write("##gff-version 3\n")
    for chrom, bed_start, bed_end in enhancers_bed:
        gff_start = bed_start + 1
        gff_end = bed_end
        f.write(f"{chrom}\tprediction\tenhancer\t{gff_start}\t{gff_end}\t.\t.\t.\tID=enh_{chrom}_{bed_start}\n")

# === CpG Islands (BED3, chr prefix, UNSORTED) ===
cpg_islands = [
    ("chr1", 3000, 5500),
    ("chr1", 22000, 24500),
    ("chr1", 34000, 36500),
    ("chr1", 63000, 66000),
    ("chr1", 89000, 92500),
    ("chr2", 4000, 6000),
    ("chr2", 29000, 31500),
    ("chr2", 43000, 46000),
    ("chr2", 70000, 73000),
    ("chr3", 4000, 6000),
    ("chr3", 14000, 16000),
    ("chr3", 27000, 29500),
    ("chr3", 40000, 43000),
    ("chr3", 51000, 53500),
]
random.shuffle(cpg_islands)
with open('/app/data/cpg_islands.bed', 'w') as f:
    for chrom, start, end in cpg_islands:
        f.write(f"{chrom}\t{start}\t{end}\n")

# === Repeats (BED3, chr prefix, sorted) ===
repeats = [
    ("chr1", 3200, 3800),
    ("chr1", 23500, 24200),
    ("chr1", 35500, 36200),
    ("chr1", 90500, 91200),
    ("chr2", 4800, 5300),
    ("chr2", 30000, 30800),
    ("chr2", 44500, 45000),
    ("chr2", 71500, 72000),
    ("chr3", 4300, 4800),
    ("chr3", 27500, 28200),
    ("chr3", 41500, 42000),
    ("chr3", 52000, 52300),
]
with open('/app/data/repeats.bed', 'w') as f:
    for chrom, start, end in repeats:
        f.write(f"{chrom}\t{start}\t{end}\n")

# === Variants (BED4, NO "chr" prefix, WITH duplicates, sorted) ===
reg_variants = [
    ("1", 3100, 3101, "var_1_3100"),
    ("1", 4000, 4001, "var_1_4000"),
    ("1", 5000, 5001, "var_1_5000"),
    ("1", 24300, 24301, "var_1_24300"),
    ("1", 36300, 36301, "var_1_36300"),
    ("1", 64500, 64501, "var_1_64500"),
    ("1", 65000, 65001, "var_1_65000"),
    ("1", 90200, 90201, "var_1_90200"),
    ("1", 91500, 91501, "var_1_91500"),
    ("2", 4200, 4201, "var_2_4200"),
    ("2", 43500, 43501, "var_2_43500"),
    ("2", 45200, 45201, "var_2_45200"),
    ("2", 70500, 70501, "var_2_70500"),
    ("2", 72100, 72101, "var_2_72100"),
    ("3", 4100, 4101, "var_3_4100"),
    ("3", 27200, 27201, "var_3_27200"),
    ("3", 28300, 28301, "var_3_28300"),
    ("3", 40500, 40501, "var_3_40500"),
    ("3", 42200, 42201, "var_3_42200"),
]
nonreg_variants = [
    ("1", 1000, 1001, "var_1_1000"),
    ("1", 7500, 7501, "var_1_7500"),
    ("1", 14000, 14001, "var_1_14000"),
    ("1", 18000, 18001, "var_1_18000"),
    ("1", 30000, 30001, "var_1_30000"),
    ("1", 45000, 45001, "var_1_45000"),
    ("1", 55000, 55001, "var_1_55000"),
    ("1", 60000, 60001, "var_1_60000"),
    ("1", 75000, 75001, "var_1_75000"),
    ("1", 85000, 85001, "var_1_85000"),
    ("1", 95000, 95001, "var_1_95000"),
    ("2", 1000, 1001, "var_2_1000"),
    ("2", 8000, 8001, "var_2_8000"),
    ("2", 15000, 15001, "var_2_15000"),
    ("2", 25000, 25001, "var_2_25000"),
    ("2", 38000, 38001, "var_2_38000"),
    ("2", 50000, 50001, "var_2_50000"),
    ("2", 55000, 55001, "var_2_55000"),
    ("2", 68000, 68001, "var_2_68000"),
    ("2", 75000, 75001, "var_2_75000"),
    ("3", 2000, 2001, "var_3_2000"),
    ("3", 12000, 12001, "var_3_12000"),
    ("3", 20000, 20001, "var_3_20000"),
    ("3", 35000, 35001, "var_3_35000"),
    ("3", 50000, 50001, "var_3_50000"),
    ("3", 55000, 55001, "var_3_55000"),
]

all_variants = reg_variants + nonreg_variants

# Add exact duplicate entries
duplicates = [
    ("1", 3100, 3101, "var_1_3100"),
    ("1", 36300, 36301, "var_1_36300"),
    ("2", 43500, 43501, "var_2_43500"),
    ("1", 1000, 1001, "var_1_1000"),
    ("1", 45000, 45001, "var_1_45000"),
    ("2", 8000, 8001, "var_2_8000"),
    ("3", 2000, 2001, "var_3_2000"),
    ("3", 40500, 40501, "var_3_40500"),
]

all_with_dupes = all_variants + duplicates
all_with_dupes.sort(key=lambda x: (x[0], x[1]))

with open('/app/data/variants.bed', 'w') as f:
    for chrom, start, end, name in all_with_dupes:
        f.write(f"{chrom}\t{start}\t{end}\t{name}\n")

# === README ===
with open('/app/data/README.txt', 'w') as f:
    f.write("""Sequencing Study - Regulatory Variant Analysis
================================================

This directory contains genomic annotation data and variant calls
from a sequencing study. Data was assembled from multiple sources
and analysis pipelines. Some data normalization may be needed
before cross-referencing different files.

Files:
  variants.bed    - Variant calls (BED format)
  promoters.bed   - Promoter region annotations
  enhancers.gff   - Enhancer region annotations (GFF3)
  cpg_islands.bed - CpG island annotations
  repeats.bed     - Repeat element annotations
  genes.bed       - Gene annotations (BED6)
  expression.tsv  - Gene expression measurements (FPKM)
  genome.txt      - Chromosome sizes
""")
