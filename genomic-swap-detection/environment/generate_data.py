#!/usr/bin/env python3
"""Generate synthetic multi-sample VCF and associated files for relatedness analysis task.

Creates a cohort of 6 samples forming 2 families with specific genetic relationships.
The pedigree file is intentionally incorrect (mothers swapped between families).
Output VCF is bgzipped and tabix-indexed.
"""

import random
import os
import subprocess

random.seed(20240315)

SAMPLES = ["S1", "S2", "S3", "S4", "S5", "S6"]
NUM_SITES = 200

os.makedirs("/app", exist_ok=True)
os.makedirs("/app/results", exist_ok=True)


def draw_gt(af):
    """Draw a genotype from Hardy-Weinberg equilibrium given alt allele frequency."""
    r = random.random()
    p = 1 - af
    if r < p * p:
        return (0, 0)
    elif r < p * p + 2 * p * af:
        return (0, 1)
    else:
        return (1, 1)


def transmit(gt):
    """Transmit one allele from a parent genotype."""
    return gt[random.randint(0, 1)]


def make_child(p1, p2):
    """Generate child genotype from two parent genotypes via Mendelian transmission."""
    a1 = transmit(p1)
    a2 = transmit(p2)
    return tuple(sorted([a1, a2]))


# Generate site information and genotypes
sites = []
genotypes = {s: [] for s in SAMPLES}
pop_afs = []

bases = ["A", "C", "G", "T"]
alt_map = {"A": "G", "C": "T", "G": "A", "T": "C"}

for i in range(NUM_SITES):
    chrom = "chr{}".format((i // 40) + 1)
    pos = (i % 40) * 2500 + 1000
    ref = bases[i % 4]
    alt = alt_map[ref]

    af = random.uniform(0.2, 0.8)
    pop_afs.append(round(af, 6))
    sites.append((chrom, pos, ref, alt))

    # S1 and S4 are brothers (share grandparents)
    gp1 = draw_gt(af)
    gp2 = draw_gt(af)
    s1_gt = make_child(gp1, gp2)
    s4_gt = make_child(gp1, gp2)

    # S2 and S5 are unrelated founders
    s2_gt = draw_gt(af)
    s5_gt = draw_gt(af)

    # S3 = child of S1 + S2, S6 = child of S4 + S5
    s3_gt = make_child(s1_gt, s2_gt)
    s6_gt = make_child(s4_gt, s5_gt)

    genotypes["S1"].append(s1_gt)
    genotypes["S2"].append(s2_gt)
    genotypes["S3"].append(s3_gt)
    genotypes["S4"].append(s4_gt)
    genotypes["S5"].append(s5_gt)
    genotypes["S6"].append(s6_gt)

# Inject de novo variants in S3 (child is het, both true parents hom-ref)
for idx in [180, 185, 190]:
    genotypes["S1"][idx] = (0, 0)
    genotypes["S2"][idx] = (0, 0)
    genotypes["S3"][idx] = (0, 1)
    pop_afs[idx] = 0.0001

# Inject compound het pattern in S3 within a gene region on chr2
# Site 50: inherited from father (S1 het, S2 hom-ref)
genotypes["S1"][50] = (0, 1)
genotypes["S2"][50] = (0, 0)
genotypes["S3"][50] = (0, 1)
pop_afs[50] = 0.002

# Site 55: inherited from mother (S1 hom-ref, S2 het)
genotypes["S1"][55] = (0, 0)
genotypes["S2"][55] = (0, 1)
genotypes["S3"][55] = (0, 1)
pop_afs[55] = 0.003

# === Write VCF ===
with open("/app/cohort.vcf", "w") as f:
    f.write("##fileformat=VCFv4.2\n")
    f.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
    f.write('##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n')
    f.write('##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n')
    f.write('##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n')
    for c in range(1, 6):
        f.write("##contig=<ID=chr{}>\n".format(c))
    f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" +
            "\t".join(SAMPLES) + "\n")

    for i, (chrom, pos, ref, alt) in enumerate(sites):
        gt_fields = []
        for s in SAMPLES:
            gt = genotypes[s][i]
            gt_str = "{}/{}".format(gt[0], gt[1])
            dp = random.randint(20, 60)
            gq = random.randint(30, 99)
            if gt == (0, 0):
                ad = "{},0".format(dp)
            elif gt == (0, 1):
                ref_d = dp // 2
                ad = "{},{}".format(ref_d, dp - ref_d)
            else:
                ad = "0,{}".format(dp)
            gt_fields.append("{}:{}:{}:{}".format(gt_str, dp, gq, ad))

        f.write("{}\t{}\t.\t{}\t{}\t100\tPASS\t.\tGT:DP:GQ:AD\t".format(
            chrom, pos, ref, alt) + "\t".join(gt_fields) + "\n")

# === Bgzip and tabix index the VCF ===
subprocess.run(["bgzip", "/app/cohort.vcf"], check=True)
subprocess.run(["tabix", "-p", "vcf", "/app/cohort.vcf.gz"], check=True)

# === Write incorrect pedigree (S2 and S5 swapped between families) ===
with open("/app/pedigree.ped", "w") as f:
    f.write("#family_id\tsample_id\tpaternal_id\tmaternal_id\tsex\tphenotype\n")
    f.write("FAM1\tS1\t0\t0\t1\t1\n")
    f.write("FAM1\tS5\t0\t0\t2\t1\n")
    f.write("FAM1\tS3\tS1\tS5\t2\t2\n")
    f.write("FAM2\tS4\t0\t0\t1\t1\n")
    f.write("FAM2\tS2\t0\t0\t2\t1\n")
    f.write("FAM2\tS6\tS4\tS2\t1\t1\n")

# === Write gene annotations (BED format: 0-based start, exclusive end) ===
with open("/app/genes.bed", "w") as f:
    f.write("#chrom\tstart\tend\tgene_name\n")
    f.write("chr1\t0\t100000\tGENE_ALPHA\n")
    f.write("chr2\t25000\t40000\tDISEASE_GENE_A\n")
    f.write("chr2\t60000\t100000\tGENE_BETA\n")
    f.write("chr3\t0\t100000\tGENE_GAMMA\n")
    f.write("chr4\t0\t100000\tGENE_DELTA\n")
    f.write("chr5\t0\t100000\tGENE_EPSILON\n")

# === Write population allele frequencies ===
with open("/app/population_af.tsv", "w") as f:
    f.write("#chrom\tpos\tref\talt\taf\n")
    for i, (chrom, pos, ref, alt) in enumerate(sites):
        f.write("{}\t{}\t{}\t{}\t{}\n".format(chrom, pos, ref, alt, pop_afs[i]))
