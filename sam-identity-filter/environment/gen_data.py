#!/usr/bin/env python3
"""Generate reference genome, BAM file, and indexes for the alignment audit task.

"""
import os
import subprocess


def seq(n):
    """Generate a DNA sequence of length n."""
    bases = "ACGTACGTACGTACGT"
    return (bases * ((n // len(bases)) + 1))[:n]


os.makedirs("/app", exist_ok=True)

# Create reference genome
with open("/app/reference.fa", "w") as f:
    f.write(">chr1\n")
    f.write(seq(10000) + "\n")
    f.write(">chr2\n")
    f.write(seq(8000) + "\n")

# Index reference
subprocess.run(["samtools", "faidx", "/app/reference.fa"], check=True)

# Create SAM records
sam_lines = [
    "@HD\tVN:1.6\tSO:coordinate",
    "@SQ\tSN:chr1\tLN:10000",
    "@SQ\tSN:chr2\tLN:8000",
    # read01: Perfect alignment, 50M, NM=0
    "read01\t0\tchr1\t100\t60\t50M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:0",
    # read02: Mismatches only, 50M, NM=3
    "read02\t0\tchr1\t200\t60\t50M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:3",
    # read03: Deletion, 20M3D30M, NM=4
    "read03\t0\tchr1\t300\t60\t20M3D30M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:4",
    # read04: Insertion, 25M2I23M, NM=2
    "read04\t0\tchr1\t400\t60\t25M2I23M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:2",
    # read05: Complex CIGAR with multiple gap events, 18M3D2M2D2M1I22M, NM=7
    "read05\t0\tchr1\t500\t60\t18M3D2M2D2M1I22M\t*\t0\t0\t" + seq(45) + "\t*\tNM:i:7",
    # read06: Extended CIGAR, no gaps, 15=2X3=1X29=, NM=3
    "read06\t0\tchr1\t600\t60\t15=2X3=1X29=\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:3",
    # read07: Extended CIGAR with gaps, 10=1X5=2I3=4D25=, NM=7
    "read07\t0\tchr1\t700\t60\t10=1X5=2I3=4D25=\t*\t0\t0\t" + seq(46) + "\t*\tNM:i:7",
    # read08: Soft-clipped, 5S40M5S, NM=2
    "read08\t0\tchr1\t800\t60\t5S40M5S\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:2",
    # read09: Hard-clipped, 10H40M, NM=1
    "read09\t0\tchr1\t900\t60\t10H40M\t*\t0\t0\t" + seq(40) + "\t*\tNM:i:1",
    # read10: Chimeric primary with SA tag, 30M20S, NM=1
    "read10\t0\tchr1\t1000\t60\t30M20S\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:1\tSA:Z:chr2,500,+,20S30M,60,2;",
    # read10: Supplementary (flag 2048), 20S30M, NM=2
    "read10\t2048\tchr2\t500\t60\t20S30M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:2",
    # read11: Secondary (flag 256) - intentionally placed before primary
    "read11\t256\tchr1\t1100\t0\t50M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:5",
    # read11: Primary
    "read11\t0\tchr1\t1050\t60\t50M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:2",
    # read12: Unmapped (flag 4)
    "read12\t4\t*\t0\t0\t*\t*\t0\t0\t" + seq(50) + "\t*",
    # read13: Multiple gaps, 10M2I5M3D10M1I5M4D15M, NM=12
    "read13\t0\tchr2\t100\t60\t10M2I5M3D10M1I5M4D15M\t*\t0\t0\t" + seq(48) + "\t*\tNM:i:12",
    # read14: High error rate, 50M, NM=15
    "read14\t0\tchr2\t200\t60\t50M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:15",
    # read15: Large single insertion, 20M10I20M, NM=11
    "read15\t0\tchr2\t300\t60\t20M10I20M\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:11",
    # read16: Extended complex, 5=1X10=3I2=2X8=5D20=, NM=11
    "read16\t0\tchr2\t400\t60\t5=1X10=3I2=2X8=5D20=\t*\t0\t0\t" + seq(51) + "\t*\tNM:i:11",
    # read17: Extended CIGAR with WRONG NM (given 5, correct is 3)
    "read17\t0\tchr2\t500\t60\t20=1X10=2X17=\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:5",
    # read18: Extended CIGAR with WRONG NM (given 12, correct is 9)
    "read18\t0\tchr2\t600\t60\t8=2X5=3I10=1X2D15=1X5=\t*\t0\t0\t" + seq(50) + "\t*\tNM:i:12",
]

# Write SAM to temp file
with open("/tmp/alignments.sam", "w") as f:
    for line in sam_lines:
        f.write(line + "\n")

# Convert to sorted BAM with index
subprocess.run(
    ["samtools", "view", "-bS", "/tmp/alignments.sam", "-o", "/tmp/unsorted.bam"],
    check=True,
)
subprocess.run(
    ["samtools", "sort", "/tmp/unsorted.bam", "-o", "/app/alignments.bam"],
    check=True,
)
subprocess.run(["samtools", "index", "/app/alignments.bam"], check=True)

# Cleanup intermediates
os.remove("/tmp/alignments.sam")
os.remove("/tmp/unsorted.bam")
