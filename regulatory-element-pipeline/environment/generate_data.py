#!/usr/bin/env python3
"""Generate synthetic genomic data with planted quality issues for audit task."""
import random
import os


def main():
    DATA_DIR = "/app/data"
    os.makedirs(DATA_DIR, exist_ok=True)

    # True chromosome sizes (used for data generation)
    CHROMS = [
        ("chr1", 250000),
        ("chr2", 200000),
        ("chr3", 150000),
        ("chr4", 100000),
        ("chr5", 50000),
    ]
    total_genome = sum(s for _, s in CHROMS)
    chrom_dict = dict(CHROMS)

    # ===== DEFECT 4: Write genome.txt with INCORRECT chr3 size =====
    # chr3 is listed as 100000 instead of the true 150000.
    # This causes bedtools complement/flank to clip at the wrong boundary.
    with open(os.path.join(DATA_DIR, "genome.txt"), "w") as f:
        for name, size in CHROMS:
            written_size = 100000 if name == "chr3" else size
            f.write(f"{name}\t{written_size}\n")

    def place_intervals(rng, chrom_size, n, min_size, max_size, margin,
                        min_gap=200, max_gap=2000):
        """Place up to n non-overlapping intervals on a chromosome."""
        results = []
        pos = margin + rng.randint(0, min(500, margin))
        for _ in range(n):
            pos += rng.randint(min_gap, max_gap)
            if pos + min_size >= chrom_size - margin:
                break
            size = rng.randint(min_size, max_size)
            end = min(pos + size, chrom_size - margin)
            if end <= pos:
                break
            results.append((pos, end))
            pos = end
        return results

    # === GENES (BED6: chrom, start, end, name, score, strand) ===
    rng_genes = random.Random(42)
    genes = []
    gene_idx = 1
    for chrom, chrom_size in CHROMS:
        n = max(3, chrom_size // 20000)
        intervals = place_intervals(rng_genes, chrom_size, n, 3000, 18000,
                                    3000, 2500, 8000)
        for start, end in intervals:
            strand = rng_genes.choice(["+", "-"])
            genes.append((chrom, start, end,
                          f"GENE{gene_idx:03d}", "0", strand))
            gene_idx += 1

    # ===== DEFECT 1: Corrupt strand encoding for 5 genes =====
    # Replace "+" with "1" and "-" with "-1" — a common artifact
    # from incorrect GFF3-to-BED conversion. bedtools flank -s does
    # not recognize "1"/"-1" as valid strand values.
    rng_defect = random.Random(999)
    n_strand_defects = min(5, len(genes))
    defect_indices = sorted(rng_defect.sample(range(len(genes)),
                                              n_strand_defects))
    for i in defect_indices:
        g = list(genes[i])
        g[5] = "1" if g[5] == "+" else "-1"
        genes[i] = tuple(g)

    with open(os.path.join(DATA_DIR, "genes.bed"), "w") as f:
        for g in genes:
            f.write("\t".join(str(x) for x in g) + "\n")

    # === CpG ISLANDS (BED4: chrom, start, end, name) ===
    rng_cpg = random.Random(142)
    cpg = []
    cpg_idx = 1
    for chrom, chrom_size in CHROMS:
        n = max(5, chrom_size // 10000)
        intervals = place_intervals(rng_cpg, chrom_size, n, 200, 1200,
                                    200, 500, 3000)
        for start, end in intervals:
            cpg.append((chrom, start, end, f"CpG_{cpg_idx:03d}"))
            cpg_idx += 1

    # ===== DEFECT 2: Write CpG islands with 1-based starts =====
    # Simulates incomplete GFF3-to-BED conversion: the start coordinate
    # was not adjusted from 1-based (GFF3) to 0-based (BED). Each CpG
    # island start is off by +1, making all islands 1bp shorter and
    # shifted 1bp right. This causes systematically reduced intersection
    # counts with other annotation tracks.
    with open(os.path.join(DATA_DIR, "cpg_islands.bed"), "w") as f:
        for c in cpg:
            f.write(f"{c[0]}\t{c[1] + 1}\t{c[2]}\t{c[3]}\n")

    # === REPEATS (BED4: chrom, start, end, name) ===
    rng_rep = random.Random(242)
    reps = []
    rep_idx = 1
    for chrom, chrom_size in CHROMS:
        n = max(5, chrom_size // 6000)
        intervals = place_intervals(rng_rep, chrom_size, n, 100, 2000,
                                    100, 200, 1500)
        for start, end in intervals:
            reps.append((chrom, start, end, f"REP_{rep_idx:03d}"))
            rep_idx += 1
    with open(os.path.join(DATA_DIR, "repeats.bed"), "w") as f:
        for r in reps:
            f.write("\t".join(str(x) for x in r) + "\n")

    # === SHARED REGULATORY HOTSPOTS ===
    rng_hot = random.Random(342)
    hotspots = []
    for chrom, chrom_size in CHROMS:
        n = max(5, chrom_size // 3000)
        intervals = place_intervals(rng_hot, chrom_size, n, 150, 500,
                                    100, 200, 1500)
        for start, end in intervals:
            hotspots.append((chrom, start, end))

    # === TFBS FILES (BED5: chrom, start, end, name, score) ===
    def generate_tfbs(prefix, seed, hotspot_prob, n_unique):
        rng = random.Random(seed)
        peaks = []
        peak_idx = 1

        # Sample from shared hotspots
        for chrom, start, end in hotspots:
            if rng.random() < hotspot_prob:
                js = rng.randint(-20, 20)
                je = rng.randint(-20, 20)
                s = max(0, start + js)
                e = min(chrom_dict[chrom], end + je)
                if e > s:
                    score = rng.randint(100, 1000)
                    peaks.append((chrom, s, e,
                                  f"{prefix}_{peak_idx:03d}", score))
                    peak_idx += 1

        # Add unique peaks per chromosome
        for chrom, chrom_size in CHROMS:
            nu = max(2, int(n_unique * chrom_size / total_genome))
            intervals = place_intervals(rng, chrom_size, nu, 100, 400,
                                        50, 300, 2000)
            for start, end in intervals:
                score = rng.randint(100, 1000)
                peaks.append((chrom, start, end,
                              f"{prefix}_{peak_idx:03d}", score))
                peak_idx += 1

        # Sort by chrom then start
        peaks.sort(key=lambda x: (x[0], x[1]))
        # Remove overlapping peaks (keep first)
        cleaned = []
        for p in peaks:
            if cleaned and p[0] == cleaned[-1][0] and p[1] < cleaned[-1][2]:
                continue
            cleaned.append(p)
        return cleaned

    # TF_A and TF_B: high hotspot sampling -> similar to each other
    # TF_C and TF_D: moderate hotspot sampling
    # TF_E: low hotspot sampling, more unique peaks
    tfbs = {}
    tfbs["A"] = generate_tfbs("TFA", 1000, 0.65, 40)
    tfbs["B"] = generate_tfbs("TFB", 2000, 0.60, 45)
    tfbs["C"] = generate_tfbs("TFC", 3000, 0.45, 50)
    tfbs["D"] = generate_tfbs("TFD", 4000, 0.40, 55)
    tfbs["E"] = generate_tfbs("TFE", 5000, 0.25, 60)

    # ===== DEFECT 3: Shuffle tfbs_C (destroy sort order) =====
    # bedtools jaccard and multiinter require sorted input.
    # Unsorted tfbs_C.bed will cause incorrect or failed results
    # for any operation that depends on sorted input.
    rng_shuffle = random.Random(7777)
    rng_shuffle.shuffle(tfbs["C"])

    # ===== DEFECT 5: Corrupt chromosome names in tfbs_D =====
    # Change "chr3" to "Chr3" and "chr5" to "Chr5" in tfbs_D entries.
    # bedtools requires exact string matching for chromosome names.
    # Mismatched names silently produce zero overlaps, causing
    # chromosome-specific gaps in Jaccard, coverage, and map outputs.
    corrupted_d = []
    for entry in tfbs["D"]:
        chrom = entry[0]
        if chrom in ("chr3", "chr5"):
            chrom = "C" + chrom[1:]  # chr3 -> Chr3, chr5 -> Chr5
        corrupted_d.append((chrom,) + entry[1:])
    tfbs["D"] = corrupted_d

    for name in sorted(tfbs.keys()):
        with open(os.path.join(DATA_DIR, f"tfbs_{name}.bed"), "w") as f:
            for t in tfbs[name]:
                f.write("\t".join(str(x) for x in t) + "\n")

    # === WRITE ANALYST NOTES ===
    with open("/app/NOTES.txt", "w") as f:
        f.write(
            "Previous analysis attempt — debug notes\n"
            "==========================================\n"
            "\n"
            "Ran a bedtools regulatory analysis pipeline on this dataset.\n"
            "Multiple anomalies observed across outputs:\n"
            "\n"
            "1. Jaccard similarity: Matrix is asymmetric for sample pairs\n"
            "   involving C (reversed sample order gives different values).\n"
            "   Sample D shows zero overlap with all other samples on\n"
            "   certain chromosomes but normal values on others — yet D\n"
            "   has peaks on all chromosomes, so this is unexpected.\n"
            "\n"
            "2. Promoter extraction (bedtools flank -s): Five genes produce\n"
            "   promoter intervals on the wrong side of the gene body.\n"
            "   Their promoter windows appear downstream rather than\n"
            "   upstream, as if strand is being ignored for those records.\n"
            "\n"
            "3. CpG island overlaps: Intersection counts between promoters\n"
            "   and CpG islands are consistently lower than expected.\n"
            "   Cross-referencing individual islands against a known database\n"
            "   suggests systematic coordinate misalignment — each island\n"
            "   appears shifted by a small fixed offset relative to other\n"
            "   genomic annotations in the dataset.\n"
            "\n"
            "4. Genome boundaries: bedtools complement produces unexpected\n"
            "   output for chr3 — a large desert appears beyond position\n"
            "   100000. Some TFBS peaks on chr3 are flagged as exceeding\n"
            "   the chromosome length recorded in genome.txt.\n"
            "\n"
            "5. Multi-coverage: Per-chromosome counts of bases covered by\n"
            "   3+ experiments appear low on the same chromosomes where\n"
            "   sample D shows zero Jaccard overlap. Likely related.\n"
            "\n"
            "Data was assembled from heterogeneous upstream sources\n"
            "(UCSC, ENCODE, custom GFF3 conversions). Input file formats\n"
            "and naming conventions were not validated before use.\n"
        )

    os.makedirs("/app/results", exist_ok=True)

    print(f"Data generated in {DATA_DIR}")
    print(f"Genome: {len(CHROMS)} chromosomes, {total_genome} bp total")
    print(f"Genes: {len(genes)} ({n_strand_defects} with corrupted strand)")
    print(f"CpG islands: {len(cpg)} (all with 1-based start defect)")
    print(f"Repeats: {len(reps)}")
    print(f"Hotspots: {len(hotspots)}")
    for n in "ABCDE":
        print(f"TFBS_{n}: {len(tfbs[n])} peaks")
    print(f"Defects planted: strand encoding, CpG 1-based coords, "
          f"sort order, genome size, chrom naming")


if __name__ == "__main__":
    main()
