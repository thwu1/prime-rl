#!/usr/bin/env python3
"""GIAB-style benchmark region construction pipeline.

Usage: python3 pipeline.py <config.json> <output_dir>

Reads an exclusion configuration, progressively constructs benchmark
regions by excluding annotated difficult genomic areas, filters variants
to benchmark regions, and computes stratified variant statistics.
"""

import gzip
import json
import os
import sys


def read_bed(filepath):
    """Read a BED file, returning list of (chrom, start, end) tuples."""
    intervals = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            intervals.append((parts[0], int(parts[1]), int(parts[2])))
    return intervals


def filter_by_min_length(intervals, min_length):
    """Keep only intervals with length >= min_length."""
    if min_length <= 0:
        return intervals
    return [(c, s, e) for c, s, e in intervals if (e - s) >= min_length]


def apply_slop(intervals, slop_bp, ref_length):
    """Expand each interval by slop_bp on both sides, clip to [0, ref_length)."""
    if slop_bp <= 0:
        return intervals
    return [
        (c, max(0, s - slop_bp), min(ref_length, e + slop_bp))
        for c, s, e in intervals
    ]


def merge_intervals(intervals, merge_distance=0):
    """Merge intervals where gap <= merge_distance."""
    if not intervals:
        return []
    sorted_ivls = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged = [list(sorted_ivls[0])]
    for chrom, start, end in sorted_ivls[1:]:
        prev = merged[-1]
        if chrom == prev[0] and start <= prev[2] + merge_distance:
            prev[2] = max(prev[2], end)
        else:
            merged.append([chrom, start, end])
    return [(c, s, e) for c, s, e in merged]


def subtract_intervals(benchmark, to_remove):
    """Subtract to_remove intervals from benchmark intervals."""
    if not to_remove:
        return benchmark[:]
    result = []
    to_remove_sorted = sorted(to_remove, key=lambda x: x[1])
    for chrom, b_start, b_end in benchmark:
        current_start = b_start
        for _, r_start, r_end in to_remove_sorted:
            if r_end <= current_start:
                continue
            if r_start >= b_end:
                break
            if r_start > current_start:
                result.append((chrom, current_start, r_start))
            current_start = max(current_start, r_end)
        if current_start < b_end:
            result.append((chrom, current_start, b_end))
    return result


def coverage(intervals):
    """Total bases covered by intervals."""
    return sum(end - start for _, start, end in intervals)


def position_in_intervals(pos_0based, intervals):
    """Check if a 0-based position falls within any interval [start, end)."""
    for _, start, end in intervals:
        if start <= pos_0based < end:
            return True
        if start > pos_0based:
            break
    return False


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <config.json> <output_dir>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    output_dir = sys.argv[2]

    with open(config_path) as f:
        config = json.load(f)

    ref_name = config["reference_name"]
    ref_length = config["reference_length"]

    benchmark = [(ref_name, 0, ref_length)]
    cumulative_excluded = 0
    stats_rows = []

    for step in config["steps"]:
        old_cov = coverage(benchmark)
        intervals = read_bed(step["file"])
        intervals = filter_by_min_length(intervals, step.get("min_length", 0))
        intervals = apply_slop(intervals, step.get("slop_bp", 0), ref_length)
        intervals = merge_intervals(intervals, step.get("merge_distance", 0))
        benchmark = subtract_intervals(benchmark, intervals)
        new_cov = coverage(benchmark)
        bases_excluded = old_cov - new_cov
        cumulative_excluded += bases_excluded
        stats_rows.append({
            "step_name": step["name"],
            "bases_excluded": bases_excluded,
            "cumulative_excluded": cumulative_excluded,
            "remaining_bases": new_cov,
        })

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "benchmark_regions.bed"), "w") as f:
        for chrom, start, end in benchmark:
            f.write(f"{chrom}\t{start}\t{end}\n")

    with open(os.path.join(output_dir, "exclusion_stats.tsv"), "w") as f:
        f.write("step_name\tbases_excluded\tcumulative_excluded\tremaining_bases\n")
        for row in stats_rows:
            f.write(
                f"{row['step_name']}\t{row['bases_excluded']}\t"
                f"{row['cumulative_excluded']}\t{row['remaining_bases']}\n"
            )

    benchmark_sorted = sorted(benchmark, key=lambda x: x[1])
    header_lines = []
    benchmark_variants = []

    variants_file = config["variants_file"]
    opener = (
        gzip.open(variants_file, "rt")
        if variants_file.endswith(".gz")
        else open(variants_file)
    )
    with opener as f:
        for line in f:
            if line.startswith("#"):
                header_lines.append(line)
                continue
            parts = line.strip().split("\t")
            pos = int(parts[1])
            pos_0based = pos - 1
            if position_in_intervals(pos_0based, benchmark_sorted):
                benchmark_variants.append(line)

    with open(os.path.join(output_dir, "benchmark_variants.vcf"), "w") as f:
        for line in header_lines:
            f.write(line)
        for line in benchmark_variants:
            f.write(line)

    snp_count = 0
    indel_count = 0
    het_count = 0
    hom_alt_count = 0

    strat_files = config.get("stratification_files", {})
    homopolymer_intervals = (
        read_bed(strat_files["homopolymers"]) if "homopolymers" in strat_files else []
    )
    small_tr_intervals = (
        read_bed(strat_files["small_tandem_repeats"])
        if "small_tandem_repeats" in strat_files
        else []
    )
    homopolymer_intervals.sort(key=lambda x: x[1])
    small_tr_intervals.sort(key=lambda x: x[1])

    in_homopolymer = 0
    in_small_tr = 0

    for line in benchmark_variants:
        parts = line.strip().split("\t")
        pos = int(parts[1])
        ref = parts[3]
        alt = parts[4]
        format_fields = parts[8].split(":")
        sample_fields = parts[9].split(":")
        gt_idx = format_fields.index("GT")
        gt = sample_fields[gt_idx]

        if len(ref) == 1 and len(alt) == 1:
            snp_count += 1
        else:
            indel_count += 1

        if gt in ("0/1", "0|1", "1|0"):
            het_count += 1
        elif gt in ("1/1", "1|1"):
            hom_alt_count += 1

        pos_0based = pos - 1
        if position_in_intervals(pos_0based, homopolymer_intervals):
            in_homopolymer += 1
        if position_in_intervals(pos_0based, small_tr_intervals):
            in_small_tr += 1

    total_variants = len(benchmark_variants)
    benchmark_bp = coverage(benchmark)
    benchmark_pct = round(benchmark_bp / ref_length * 100, 2)

    summary = {
        "total_variants": total_variants,
        "snp_count": snp_count,
        "indel_count": indel_count,
        "het_count": het_count,
        "hom_alt_count": hom_alt_count,
        "in_homopolymer_count": in_homopolymer,
        "in_small_tandem_repeat_count": in_small_tr,
        "benchmark_coverage_bp": benchmark_bp,
        "benchmark_coverage_pct": benchmark_pct,
    }

    with open(os.path.join(output_dir, "variant_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print(
        f"Pipeline complete: {len(benchmark)} regions, "
        f"{benchmark_bp} bp ({benchmark_pct}%), {total_variants} variants"
    )


if __name__ == "__main__":
    main()
