#!/usr/bin/env python3
"""Copy number variation detection pipeline using bedtools.

"""
import csv
import os
import subprocess

import numpy as np
from collections import defaultdict

WIN_SIZE = 1_000_000


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def find_segments(lr, min_width=5, smooth_window=7, threshold=0.15):
    """Detect CNV segments via rolling-median smoothing and thresholding."""
    n = len(lr)
    half = smooth_window // 2

    smoothed = np.array([
        np.median(lr[max(0, i - half):min(n, i + half + 1)])
        for i in range(n)
    ])

    flags = np.abs(smoothed) > threshold

    for i in range(1, n - 1):
        if not flags[i] and flags[i - 1] and flags[i + 1]:
            flags[i] = True

    segments = []
    start = None
    for i in range(n):
        if flags[i] and start is None:
            start = i
        elif not flags[i] and start is not None:
            if i - start >= min_width:
                segments.append((start, i))
            start = None
    if start is not None and n - start >= min_width:
        segments.append((start, n))

    return segments


def estimate_purity_from_lr(lr_value):
    """Estimate tumor purity from a segment-level log2 ratio.

    Uses the mixture model: observed_ratio = purity * true_cn/2 + (1-purity).
    Tries the most common CN states and returns the best valid estimate.
    """
    if lr_value < -0.2:
        # Likely deletion — try CN=1 (heterozygous), then CN=0 (homozygous)
        p = 2.0 * (1.0 - 2.0 ** lr_value)
        if 0.05 < p <= 1.0:
            return p
        p = 1.0 - 2.0 ** lr_value
        if 0.05 < p <= 1.0:
            return p
    elif lr_value > 0.2:
        # Likely gain — try CN=3 (single-copy), then CN=4 (double-copy)
        p = 2.0 * (2.0 ** lr_value - 1.0)
        if 0.05 < p <= 1.0:
            return p
        p = 2.0 ** lr_value - 1.0
        if 0.05 < p <= 1.0:
            return p
    return None


def run_cmd(cmd):
    """Run a shell command, raising on failure."""
    subprocess.run(cmd, shell=True, check=True)


def main():
    # --- Read input data ---
    depth_rows = read_csv("/app/data/read_depths.csv")
    meta = read_csv("/app/data/sample_metadata.csv")

    normals = [m["sample"] for m in meta if m["type"] == "normal"]
    tumors = [m["sample"] for m in meta if m["type"] == "tumor"]

    n_win = len(depth_rows)
    chroms = [r["chromosome"] for r in depth_rows]
    starts_arr = [int(r["start"]) for r in depth_rows]
    ends_arr = [int(r["end"]) for r in depth_rows]
    gc = np.array([float(r["gc_content"]) for r in depth_rows])

    depths = {}
    for s in normals + tumors:
        depths[s] = np.array([float(r[s]) for r in depth_rows])

    # --- Normal reference (median of normals) ---
    norm_ref = np.median(np.array([depths[s] for s in normals]), axis=0)
    norm_ref[norm_ref == 0] = 1.0

    # --- Process each tumor sample ---
    os.makedirs("/app/output/per_sample", exist_ok=True)
    all_segments = []
    segment_lr_map = defaultdict(list)  # sample -> list of segment median LRs

    for sample in tumors:
        # Log2 ratio against normal reference
        ratio = depths[sample] / norm_ref
        ratio[ratio <= 0] = 0.001
        lr = np.log2(ratio)

        # GC bias correction: median log2 ratio per GC bin, then subtract
        n_bins = 20
        gc_edges = np.linspace(gc.min() - 0.001, gc.max() + 0.001, n_bins + 1)
        correction = np.zeros(n_win)
        for b in range(n_bins):
            mask = (gc >= gc_edges[b]) & (gc < gc_edges[b + 1])
            if mask.sum() > 0:
                correction[mask] = np.median(lr[mask])
        lr_corrected = lr - correction

        # Segment each chromosome
        chr_indices = defaultdict(list)
        for i in range(n_win):
            chr_indices[chroms[i]].append(i)

        sample_bed_lines = []
        for chrom in sorted(chr_indices.keys()):
            idx = chr_indices[chrom]
            chr_lr = lr_corrected[np.array(idx)]
            segments = find_segments(chr_lr)

            for seg_s, seg_e in segments:
                gi_start = idx[seg_s]
                gi_end = idx[seg_e - 1]
                seg_lr = float(np.median(chr_lr[seg_s:seg_e]))

                # Call CN with thresholds calibrated for unknown purity
                if seg_lr < -1.3:
                    cn = 0
                elif seg_lr < -0.25:
                    cn = 1
                elif seg_lr <= 0.25:
                    cn = 2
                elif seg_lr <= 0.65:
                    cn = 3
                elif seg_lr <= 1.2:
                    cn = 4
                else:
                    cn = min(8, round(2.0 * 2.0 ** seg_lr))

                if cn != 2:
                    seg_start = starts_arr[gi_start]
                    seg_end = ends_arr[gi_end]
                    cnv_type = "loss" if cn < 2 else "gain"
                    all_segments.append({
                        "sample": sample,
                        "chromosome": chrom,
                        "start": seg_start,
                        "end": seg_end,
                        "log2_ratio": f"{seg_lr:.4f}",
                        "copy_number": cn,
                    })
                    segment_lr_map[sample].append(seg_lr)
                    sample_bed_lines.append(
                        f"{chrom}\t{seg_start}\t{seg_end}\t{cnv_type}\t{cn}"
                    )

        # Write per-sample sorted BED file
        bed_path = f"/app/output/per_sample/{sample}.bed"
        with open(bed_path, "w") as f:
            for line in sample_bed_lines:
                f.write(line + "\n")

    # --- Write CNV segments CSV ---
    with open("/app/output/cnv_segments.csv", "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sample", "chromosome", "start", "end", "log2_ratio", "copy_number"
            ],
        )
        w.writeheader()
        w.writerows(all_segments)

    # --- Estimate tumor purity per sample ---
    purity_estimates = {}
    for sample in tumors:
        p_estimates = []
        for lr_val in segment_lr_map[sample]:
            p_est = estimate_purity_from_lr(lr_val)
            if p_est is not None:
                p_estimates.append(p_est)

        if p_estimates:
            p_estimates.sort()
            purity = p_estimates[len(p_estimates) // 2]
        else:
            purity = 0.5
        purity_estimates[sample] = round(purity, 3)

    with open("/app/output/purity_estimates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sample", "purity"])
        w.writeheader()
        for sample in tumors:
            w.writerow({"sample": sample, "purity": purity_estimates[sample]})

    # --- Create combined BED, sort with bedtools, bgzip, and tabix index ---
    combined_bed = "/tmp/all_cnv_segments.unsorted.bed"
    with open(combined_bed, "w") as f:
        for seg in all_segments:
            cnv_type = "loss" if int(seg["copy_number"]) < 2 else "gain"
            f.write(
                f"{seg['chromosome']}\t{seg['start']}\t{seg['end']}\t"
                f"{seg['sample']}_{cnv_type}\t{seg['copy_number']}\n"
            )

    sorted_bed = "/tmp/all_cnv_segments.sorted.bed"
    run_cmd(
        f"bedtools sort -i {combined_bed} -g /app/data/genome.chrom.sizes "
        f"> {sorted_bed}"
    )
    run_cmd(f"bgzip -c {sorted_bed} > /app/output/all_cnv_segments.bed.gz")
    run_cmd(f"tabix -p bed /app/output/all_cnv_segments.bed.gz")

    # --- Recurrence analysis (window-based overlap counting) ---
    gain_counts = defaultdict(lambda: defaultdict(set))
    loss_counts = defaultdict(lambda: defaultdict(set))

    for seg in all_segments:
        s = seg["sample"]
        chrom = seg["chromosome"]
        cn = int(seg["copy_number"])
        s_idx = int(seg["start"]) // WIN_SIZE
        e_idx = int(seg["end"]) // WIN_SIZE

        for wi in range(s_idx, e_idx):
            if cn > 2:
                gain_counts[chrom][wi].add(s)
            elif cn < 2:
                loss_counts[chrom][wi].add(s)

    recurrent_regions = []
    for alt_type, counts in [("gain", gain_counts), ("loss", loss_counts)]:
        for chrom in sorted(counts.keys()):
            sig_wins = sorted(
                w for w in counts[chrom] if len(counts[chrom][w]) >= 2
            )
            if not sig_wins:
                continue

            reg_start = sig_wins[0]
            reg_end = sig_wins[0]

            for wi in sig_wins[1:]:
                if wi <= reg_end + 2:
                    reg_end = wi
                else:
                    samples_in_region = set()
                    for w in range(reg_start, reg_end + 1):
                        samples_in_region |= counts[chrom].get(w, set())
                    recurrent_regions.append({
                        "chromosome": chrom,
                        "start": reg_start * WIN_SIZE,
                        "end": (reg_end + 1) * WIN_SIZE,
                        "n_samples": len(samples_in_region),
                        "type": alt_type,
                    })
                    reg_start = wi
                    reg_end = wi

            samples_in_region = set()
            for w in range(reg_start, reg_end + 1):
                samples_in_region |= counts[chrom].get(w, set())
            recurrent_regions.append({
                "chromosome": chrom,
                "start": reg_start * WIN_SIZE,
                "end": (reg_end + 1) * WIN_SIZE,
                "n_samples": len(samples_in_region),
                "type": alt_type,
            })

    # --- Write recurrent regions CSV ---
    with open("/app/output/recurrent_regions.csv", "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["chromosome", "start", "end", "n_samples", "type"]
        )
        w.writeheader()
        w.writerows(recurrent_regions)

    # --- Gene annotation via bedtools intersect ---
    recurrent_bed = "/tmp/recurrent_regions.bed"
    with open(recurrent_bed, "w") as f:
        for r in recurrent_regions:
            f.write(
                f"{r['chromosome']}\t{r['start']}\t{r['end']}\t"
                f"{r['type']}\t{r['n_samples']}\n"
            )

    recurrent_sorted = "/tmp/recurrent_regions.sorted.bed"
    run_cmd(
        f"bedtools sort -i {recurrent_bed} -g /app/data/genome.chrom.sizes "
        f"> {recurrent_sorted}"
    )

    intersect_output = "/tmp/gene_intersect.tsv"
    run_cmd(
        f"bedtools intersect -a {recurrent_sorted} "
        f"-b /app/data/gene_annotations.bed -wa -wb > {intersect_output}"
    )

    # Parse bedtools intersect output:
    # -wa cols (5): chrom, start, end, type, n_samples
    # -wb cols (7): chrom, start, end, gene, score, strand, role
    affected = []
    seen_genes = set()
    with open(intersect_output) as f:
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) < 12:
                continue
            region_type = fields[3]
            n_samples = fields[4]
            gene_chrom = fields[5]
            gene_name = fields[8]

            key = (gene_name, region_type)
            if key not in seen_genes:
                seen_genes.add(key)
                affected.append({
                    "gene": gene_name,
                    "chromosome": gene_chrom,
                    "region_type": region_type,
                    "n_samples": n_samples,
                })

    # --- Write affected genes CSV ---
    with open("/app/output/affected_genes.csv", "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["gene", "chromosome", "region_type", "n_samples"]
        )
        w.writeheader()
        w.writerows(affected)

    print(
        f"Done: {len(all_segments)} segments, "
        f"{len(recurrent_regions)} recurrent regions, "
        f"{len(affected)} affected genes, "
        f"purities: {purity_estimates}"
    )


if __name__ == "__main__":
    main()
