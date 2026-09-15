#!/usr/bin/env python3
"""Generate synthetic genomic data for variant annotation pipeline task.

Creates reference genome, gene annotations, and a raw VCF with deliberate
data quality issues (REF mismatches, multi-allelic record, non-normalized
indel, unsorted order) that must be discovered and resolved.
"""
import os
import sys

def revcomp(s):
    comp = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
    return ''.join(comp[b] for b in reversed(s))

CHROM = "chr1"

# ============================================================
# Gene CDS sequences (manually crafted, no internal stops)
# ============================================================

# Gene A: + strand, 2 exons (100 codons = 300bp CDS)
gene_a_cds = (
    "ATGGCTGATTGCAAGCTGGTACACTTGGAA"  # codons  1-10
    "TCCCGGAATGGCACTTACGTGCCAAGCTTT"  # codons 11-20
    "ATCGAGGCCAACTTTACAGCGGTAGTCCGA"  # codons 21-30
    "ATGACCTGCAATGTCCGTACCCTTGATGAC"  # codons 31-40
    "GGTATCAAGCTAATGCCTGTCGCCAACGAG"  # codons 41-50
    "ACTCTTAAACGCGATCACTTCAGCATTGAC"  # codons 51-60
    "GTACCAGGCAATCGTGCAACCTGTACCGCT"  # codons 61-70
    "GCCATTGGCGAATGCGTTACGCCTGATCTG"  # codons 71-80
    "AAGTTCGGTACACCATTGAGTCCGAACGCT"  # codons 81-90
    "ATTGCAGATACCGTGCTTCCCGGAACTTAA"  # codons 91-100
)
assert len(gene_a_cds) == 300

# Gene B: - strand, single exon (100 codons = 300bp CDS)
# This is the mRNA sequence (5'->3')
gene_b_mrna = (
    "ATGCCGTATAGCGCACTGTTCAATGCGATT"  # codons  1-10
    "GACTACCGTAAGGGCTCACTAACCGCGTTG"  # codons 11-20
    "GCCATTCTGCAATGGAGACCAGTTCGTACG"  # codons 21-30
    "GATCTGGACAGCTTGACTCATGCAAACGGT"  # codons 31-40
    "ACCTATCGGAATAGCCTGGAAGTTGCCTCA"  # codons 41-50
    "ACGCTTGAATGCCAGACTGGCTATCGTAAG"  # codons 51-60
    "GCCTTAGACATGCTGAGCAATGCGTCAGTT"  # codons 61-70
    "CGTACCGAATTCACAGGCATGGCTAATCTG"  # codons 71-80
    "ACGCATGGCTGTCCAGATAGCCGTTTCGAA"  # codons 81-90
    "AACTGGACTCCGACAGTTCTGCCAGGCTAA"  # codons 91-100
)
assert len(gene_b_mrna) == 300

# Gene C: + strand, single exon (100 codons = 300bp CDS)
gene_c_cds = (
    "ATGAACGTCCAGTGGCTTGACACATCCGGT"  # codons  1-10
    "AGCTTAGCAATGCTCGAATTGGCTCACCGT"  # codons 11-20
    "GATACCGGCATTCCATGCAGTGAACTGACG"  # codons 21-30
    "TTGACCAAGGCCTATTCAGGTACAGATCGT"  # codons 31-40
    "AACCTGGCATTCAGCGTACCTGAAATGGCG"  # codons 41-50
    "TTGACGCATGCAACTGGCGATCCAGTTACC"  # codons 51-60
    "CGTCTGAAGTCAGCCATTGAATGCACCGGT"  # codons 61-70
    "GATCTGACGTCAAACGGTACCGCATTGAAT"  # codons 71-80
    "CGTGCATGGCTGACCGAATTCAGCCAGATT"  # codons 81-90
    "GCACTGGATACCACGGTTCCAGGCAATTGA"  # codons 91-100
)
assert len(gene_c_cds) == 300

# ============================================================
# Build reference genome (2000bp)
# ============================================================
bg = "ACGT"

region1 = bg * 25           # 100bp, positions 1-100 (intergenic)
region2 = gene_a_cds[:150]  # 150bp, positions 101-250 (geneA exon 1)
intron_interior = (bg * 36) + "AC"  # 146bp
region3 = "GT" + intron_interior + "AG"  # 150bp, positions 251-400 (geneA intron)
assert len(region3) == 150
region4 = gene_a_cds[150:]  # 150bp, positions 401-550 (geneA exon 2)
region5 = (bg * 112) + "AC" # 450bp, positions 551-1000 (intergenic)
region6 = revcomp(gene_b_mrna)  # 300bp, positions 1001-1300 (geneB, - strand)
region7 = bg * 75           # 300bp, positions 1301-1600 (intergenic)
region8 = gene_c_cds        # 300bp, positions 1601-1900 (geneC)
region9 = bg * 25           # 100bp, positions 1901-2000 (intergenic)

genome = (region1 + region2 + region3 + region4 + region5 +
          region6 + region7 + region8 + region9)
assert len(genome) == 2000, f"Genome length is {len(genome)}, expected 2000"

# ============================================================
# Write reference FASTA
# ============================================================
os.makedirs("/app", exist_ok=True)

with open("/app/reference.fa", "w") as f:
    f.write(f">{CHROM}\n")
    for i in range(0, len(genome), 80):
        f.write(genome[i:i+80] + "\n")

# ============================================================
# Write GFF3 annotations
# ============================================================
with open("/app/annotations.gff3", "w") as f:
    f.write("##gff-version 3\n")
    f.write(f"##sequence-region {CHROM} 1 2000\n")

    # Gene A: + strand, 2 exons with intron
    f.write(f"{CHROM}\t.\tgene\t101\t550\t.\t+\t.\tID=geneA;Name=geneA\n")
    f.write(f"{CHROM}\t.\tmRNA\t101\t550\t.\t+\t.\tID=mRNA_A;Parent=geneA\n")
    f.write(f"{CHROM}\t.\texon\t101\t250\t.\t+\t.\tID=exon_A1;Parent=mRNA_A\n")
    f.write(f"{CHROM}\t.\texon\t401\t550\t.\t+\t.\tID=exon_A2;Parent=mRNA_A\n")
    f.write(f"{CHROM}\t.\tCDS\t101\t250\t.\t+\t0\tID=CDS_A1;Parent=mRNA_A\n")
    f.write(f"{CHROM}\t.\tCDS\t401\t550\t.\t+\t0\tID=CDS_A2;Parent=mRNA_A\n")

    # Gene B: - strand, single exon
    f.write(f"{CHROM}\t.\tgene\t1001\t1300\t.\t-\t.\tID=geneB;Name=geneB\n")
    f.write(f"{CHROM}\t.\tmRNA\t1001\t1300\t.\t-\t.\tID=mRNA_B;Parent=geneB\n")
    f.write(f"{CHROM}\t.\texon\t1001\t1300\t.\t-\t.\tID=exon_B1;Parent=mRNA_B\n")
    f.write(f"{CHROM}\t.\tCDS\t1001\t1300\t.\t-\t0\tID=CDS_B1;Parent=mRNA_B\n")

    # Gene C: + strand, single exon
    f.write(f"{CHROM}\t.\tgene\t1601\t1900\t.\t+\t.\tID=geneC;Name=geneC\n")
    f.write(f"{CHROM}\t.\tmRNA\t1601\t1900\t.\t+\t.\tID=mRNA_C;Parent=geneC\n")
    f.write(f"{CHROM}\t.\texon\t1601\t1900\t.\t+\t.\tID=exon_C1;Parent=mRNA_C\n")
    f.write(f"{CHROM}\t.\tCDS\t1601\t1900\t.\t+\t0\tID=CDS_C1;Parent=mRNA_C\n")

# ============================================================
# Write VCF with deliberate quality issues:
#   - 2 REF allele mismatches (pos 750, 1450)
#   - 1 multi-allelic record (pos 1604, ALT=G,T)
#   - 1 non-left-aligned indel (pos 1615 should be 1614)
#   - Unsorted variant order
# ============================================================
with open("/app/variants.vcf", "w") as f:
    f.write("##fileformat=VCFv4.2\n")
    f.write(f"##contig=<ID={CHROM},length=2000>\n")
    f.write('##INFO=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n')
    f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")

    # Variants in DELIBERATELY SCRAMBLED order
    variants = [
        (1287, genome[1286],              "A"),              # missense geneB (- strand)
        (50,   genome[49],                "A"),              # intergenic SNP
        (300,  genome[299],               "G"),              # intron variant geneA
        (750,  "G",                       "C"),              # *** REF MISMATCH (genome has T)
        (109,  genome[108],               "C"),              # synonymous geneA
        (1604, genome[1603],              "G,T"),            # *** MULTI-ALLELIC in geneC
        (407,  genome[406],               "T"),              # stop_gained geneA exon2
        (130,  genome[129],               genome[129]+"T"),  # frameshift ins geneA
        (1450, "A",                       "G"),              # *** REF MISMATCH (genome has C)
        (251,  genome[250],               "A"),              # splice_donor geneA
        (1271, genome[1270],              "G"),              # synonymous geneB (- strand)
        (1615, genome[1614],              genome[1614]*2),   # *** NON-NORMALIZED ins geneC
        (400,  genome[399],               "T"),              # splice_acceptor geneA
        (122,  genome[121],               "T"),              # missense geneA
        (1256, genome[1255:1258],         genome[1255]),     # frameshift del geneB
    ]

    for pos, ref, alt in variants:
        f.write(f"{CHROM}\t{pos}\t.\t{ref}\t{alt}\t100\tPASS\tDP=30\n")

# ============================================================
# Verification
# ============================================================
print("=== Data Generation Complete ===")
print(f"Genome length: {len(genome)}")

all_ok = True

# Verify correct REF alleles for non-issue variants
checks = {
    50: "C", 109: "T", 122: "C", 130: "A", 251: "G",
    300: "T", 400: "G", 407: "A", 1271: "A", 1287: "G", 1604: "A",
}
for pos, expected in checks.items():
    actual = genome[pos - 1]
    if actual != expected:
        print(f"  FAIL at pos {pos}: expected={expected} actual={actual}")
        all_ok = False

# Verify REF mismatches are actual mismatches
if genome[749] == "G":
    print("  FAIL: pos 750 genome base should NOT be G (need mismatch)")
    all_ok = False
else:
    print(f"  OK: pos 750 genome={genome[749]}, VCF REF=G (mismatch)")

if genome[1449] == "A":
    print("  FAIL: pos 1450 genome base should NOT be A (need mismatch)")
    all_ok = False
else:
    print(f"  OK: pos 1450 genome={genome[1449]}, VCF REF=A (mismatch)")

# Verify consecutive G's at 1614-1615 for non-normalized indel
if genome[1613] != "G" or genome[1614] != "G":
    print(f"  FAIL: pos 1614-1615 should both be G, got {genome[1613]}{genome[1614]}")
    all_ok = False
if genome[1612] == "G":
    print(f"  FAIL: pos 1613 should NOT be G (left-align must stop here)")
    all_ok = False

# Verify deletion ref
del_ref = genome[1255:1258]
if del_ref != "GCC":
    print(f"  FAIL deletion REF at 1256: {del_ref} != GCC")
    all_ok = False

if not all_ok:
    print("VERIFICATION FAILED!")
    sys.exit(1)

print("All checks passed.")
