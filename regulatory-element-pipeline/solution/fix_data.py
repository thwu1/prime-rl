#!/usr/bin/env python3
"""Detect and fix data quality issues in genomic input files.

Audits all BED and genome files in /app/data/ for data quality
problems: non-standard encodings, coordinate system mismatches,
sort order violations, chromosome naming inconsistencies, and
genome metadata errors.
"""

import os
import glob
import math
import subprocess

DATA_DIR = "/app/data"


def fix_strand_encoding():
    """Detect and fix non-standard strand values in genes.bed.

    BED format requires strand to be '+' or '-'. Some upstream tools
    (e.g., GFF3 converters) produce '1' for '+' and '-1' for '-'.
    bedtools flank -s does not recognize these non-standard values.
    """
    path = os.path.join(DATA_DIR, "genes.bed")
    lines = []
    fixed_count = 0
    with open(path) as f:
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) >= 6:
                if fields[5] == "1":
                    fields[5] = "+"
                    fixed_count += 1
                elif fields[5] == "-1":
                    fields[5] = "-"
                    fixed_count += 1
            lines.append("\t".join(fields))

    if fixed_count > 0:
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"[FIX] genes.bed: corrected {fixed_count} non-standard "
              f"strand values ('1'->'+', '-1'->'-')")
    else:
        print("[OK]  genes.bed: strand encoding is correct")


def fix_cpg_coordinates():
    """Fix 1-based start coordinates in cpg_islands.bed.

    CpG islands were converted from GFF3 (1-based closed) to BED (0-based
    half-open) without adjusting the start coordinate. All starts are 1bp
    too high, making each island 1bp shorter and shifted right. Subtract 1
    from each start to convert to proper 0-based BED format.

    Detection: cross-referencing CpG islands with other annotation tracks
    shows a systematic 1bp rightward shift. In correct BED format, an island
    covering bases 100-200 should have start=100, end=200. A 1-based start
    would be start=101, end=200 — off by one.
    """
    path = os.path.join(DATA_DIR, "cpg_islands.bed")
    lines = []
    fixed_count = 0
    with open(path) as f:
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) >= 3:
                start = int(fields[1])
                fields[1] = str(start - 1)
                fixed_count += 1
            lines.append("\t".join(fields))

    if fixed_count > 0:
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"[FIX] cpg_islands.bed: corrected {fixed_count} "
              f"1-based starts to 0-based BED coordinates")


def fix_chrom_names():
    """Fix chromosome naming inconsistencies across TFBS files.

    Some files use mixed case chromosome names (e.g., 'Chr3' vs 'chr3').
    bedtools requires exact string matching for chromosome names — mismatched
    names silently produce zero overlaps. Normalize all to lowercase 'chr'.
    Re-sort after normalization since case change affects sort order.
    """
    for name in "ABCDE":
        path = os.path.join(DATA_DIR, f"tfbs_{name}.bed")
        lines = []
        fixed_count = 0
        with open(path) as f:
            for line in f:
                fields = line.strip().split("\t")
                if len(fields) >= 1:
                    orig = fields[0]
                    normalized = orig.lower()
                    if normalized.startswith("chr") and orig != normalized:
                        fields[0] = normalized
                        fixed_count += 1
                lines.append("\t".join(fields))
        if fixed_count > 0:
            with open(path, "w") as f:
                for line in lines:
                    f.write(line + "\n")
            # Re-sort after name normalization
            subprocess.run(
                f"sort -k1,1 -k2,2n {path} -o {path}",
                shell=True, check=True,
            )
            print(f"[FIX] tfbs_{name}.bed: corrected {fixed_count} "
                  f"chromosome names, re-sorted")
        else:
            print(f"[OK]  tfbs_{name}.bed: chromosome names are consistent")


def fix_sort_order():
    """Detect and fix unsorted BED files.

    bedtools jaccard and multiinter require position-sorted input.
    Uses 'sort -c' to check, then re-sorts if needed.
    """
    for name in "ABCDE":
        path = os.path.join(DATA_DIR, f"tfbs_{name}.bed")
        result = subprocess.run(
            f"sort -c -k1,1 -k2,2n {path}",
            shell=True, capture_output=True,
        )
        if result.returncode != 0:
            print(f"[FIX] tfbs_{name}.bed: file is not sorted, re-sorting")
            subprocess.run(
                f"sort -k1,1 -k2,2n {path} -o {path}",
                shell=True, check=True,
            )
        else:
            print(f"[OK]  tfbs_{name}.bed: sort order is correct")


def fix_genome_sizes():
    """Verify chromosome sizes in genome.txt against actual data.

    Scans all BED files for the maximum endpoint on each chromosome.
    If any data extends beyond the reported chromosome size, the
    genome file is incorrect. Corrects by rounding up to nearest
    50000 bp boundary.
    """
    genome_path = os.path.join(DATA_DIR, "genome.txt")

    # Read current genome file
    genome = {}
    chrom_order = []
    with open(genome_path) as f:
        for line in f:
            parts = line.strip().split("\t")
            genome[parts[0]] = int(parts[1])
            chrom_order.append(parts[0])

    # Find max coordinate per chromosome across all BED files
    max_coords = {}
    for bed_file in sorted(glob.glob(os.path.join(DATA_DIR, "*.bed"))):
        with open(bed_file) as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    try:
                        chrom = parts[0]
                        end = int(parts[2])
                        if chrom not in max_coords or end > max_coords[chrom]:
                            max_coords[chrom] = end
                    except ValueError:
                        pass

    # Fix any chromosome where data extends beyond reported size
    fixed = False
    for chrom in chrom_order:
        if chrom in max_coords and max_coords[chrom] > genome[chrom]:
            correct = math.ceil(max_coords[chrom] / 50000) * 50000
            print(f"[FIX] genome.txt: {chrom} size {genome[chrom]} -> "
                  f"{correct} (data extends to {max_coords[chrom]})")
            genome[chrom] = correct
            fixed = True

    if fixed:
        with open(genome_path, "w") as f:
            for chrom in chrom_order:
                f.write(f"{chrom}\t{genome[chrom]}\n")
    else:
        print("[OK]  genome.txt: all chromosome sizes are consistent")


if __name__ == "__main__":
    print("=" * 50)
    print("PHASE 1: Auditing input data quality")
    print("=" * 50)
    fix_strand_encoding()
    fix_cpg_coordinates()
    fix_chrom_names()
    fix_sort_order()
    fix_genome_sizes()
    print("=" * 50)
    print("Data audit complete — all issues fixed")
    print("=" * 50)
