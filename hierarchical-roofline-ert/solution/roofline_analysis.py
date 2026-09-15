#!/usr/bin/env python3
"""Hierarchical Roofline characterization tool.

"""

import json
import os
import sys
from collections import defaultdict

import numpy as np


# ---------------------------------------------------------------------------
# ERT data parsing
# ---------------------------------------------------------------------------

def parse_ert_file(filepath):
    """Parse an ERT raw data file."""
    data = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 5:
                data.append((
                    int(parts[0]),      # ws_elements
                    int(parts[1]),      # trials
                    float(parts[2]),    # time_us
                    int(parts[3]),      # total_bytes
                    int(parts[4]),      # total_flops
                ))
    return data


def compute_bandwidth_and_gflops(data):
    """Compute bandwidth (GB/s) and GFLOP/s for each measurement."""
    results = []
    for ws_elements, trials, time_us, total_bytes, total_flops in data:
        time_s = time_us * 1e-6
        if time_s <= 0:
            continue
        results.append({
            "ws_bytes": ws_elements * 8,
            "bandwidth_gbps": total_bytes / time_s / 1e9,
            "gflops": total_flops / time_s / 1e9,
        })
    return results


# ---------------------------------------------------------------------------
# Bandwidth profile extraction
# ---------------------------------------------------------------------------

def extract_max_bandwidth_per_ws(metrics):
    """For each working-set size, return the maximum observed bandwidth."""
    ws_bw = defaultdict(float)
    for m in metrics:
        ws = m["ws_bytes"]
        if m["bandwidth_gbps"] > ws_bw[ws]:
            ws_bw[ws] = m["bandwidth_gbps"]

    ws_sorted = sorted(ws_bw.keys())
    bw_sorted = [ws_bw[ws] for ws in ws_sorted]
    return np.array(ws_sorted, dtype=float), np.array(bw_sorted)


# ---------------------------------------------------------------------------
# Cache hierarchy detection
# ---------------------------------------------------------------------------

def _running_median(arr, w=3):
    result = np.copy(arr)
    half = w // 2
    for i in range(len(arr)):
        s = max(0, i - half)
        e = min(len(arr), i + half + 1)
        result[i] = np.median(arr[s:e])
    return result


def detect_cache_levels(ws_arr, bw_arr):
    """Detect cache hierarchy levels from bandwidth-vs-working-set profile.

    Strategy:
        1. Smooth the log2(bw) curve with a running median.
        2. Compute finite differences; flag large negative drops as transitions.
        3. Merge nearby transitions.
        4. Report per-plateau bandwidth (median) and max working-set size.
    """
    log_bw = np.log2(bw_arr)
    log_bw_smooth = _running_median(log_bw, 3)

    diffs = np.diff(log_bw_smooth)

    # Detect significant negative drops
    threshold = -0.3
    transition_indices = [i + 1 for i, d in enumerate(diffs) if d < threshold]

    # Merge transitions within 2 steps
    merged = []
    for t in transition_indices:
        if merged and t - merged[-1] <= 2:
            merged[-1] = t
        else:
            merged.append(t)

    # Build plateaus
    boundaries = [0] + merged + [len(ws_arr)]
    level_names = ["L1", "L2", "L3", "DRAM", "L4", "L5"]

    levels = []
    for j in range(len(boundaries) - 1):
        start, end = boundaries[j], boundaries[j + 1]
        if start >= end:
            continue

        segment_bw = bw_arr[start:end]
        plateau_bw = float(np.median(segment_bw))

        entry = {
            "level": level_names[j] if j < len(level_names) else f"Level_{j}",
            "bandwidth_gbps": round(plateau_bw, 2),
        }

        if j < len(boundaries) - 2:  # not the last level (DRAM)
            entry["size_bytes"] = int(ws_arr[end - 1])

        levels.append(entry)

    return levels


# ---------------------------------------------------------------------------
# Peak GFLOP/s extraction
# ---------------------------------------------------------------------------

def extract_peak_gflops(ert_data_dir):
    """Extract peak GFLOP/s from the highest-FLOP ERT data file."""
    highest_flop = 0
    highest_file = None

    for fname in os.listdir(ert_data_dir):
        if fname.startswith("flop_") and fname.endswith(".dat"):
            flop = int(fname.split("_")[1].split(".")[0])
            if flop > highest_flop:
                highest_flop = flop
                highest_file = fname

    if highest_file is None:
        raise FileNotFoundError("No ERT data files found")

    data = parse_ert_file(os.path.join(ert_data_dir, highest_file))
    metrics = compute_bandwidth_and_gflops(data)

    return round(max(m["gflops"] for m in metrics), 2)


# ---------------------------------------------------------------------------
# STREAM parsing and write-allocate correction
# ---------------------------------------------------------------------------

def parse_stream(filepath):
    """Parse STREAM output; return raw bandwidths in GB/s."""
    bw = {}
    with open(filepath) as f:
        for line in f:
            for kernel in ("Copy", "Scale", "Add", "Triad"):
                if line.strip().startswith(kernel + ":"):
                    rate_mbps = float(line.split()[1])
                    bw[kernel.lower()] = rate_mbps / 1000.0
    return bw


def correct_stream(raw):
    """Apply write-allocate correction factors."""
    corrected = {
        "copy_gbps":  round(raw["copy"]  * 1.5,       6),
        "scale_gbps": round(raw["scale"] * 1.5,       6),
        "add_gbps":   round(raw["add"]   * (4.0/3.0), 6),
        "triad_gbps": round(raw["triad"] * (4.0/3.0), 6),
    }
    corrected["average_gbps"] = round(
        sum(corrected.values()) / 4.0, 6
    )
    return corrected


# ---------------------------------------------------------------------------
# Kernel classification
# ---------------------------------------------------------------------------

def classify_kernels(kernels, hierarchy, peak):
    """Classify each application kernel using the hierarchical roofline."""
    results = []
    for k in kernels:
        ai = k["total_flops"] / k["total_bytes"]
        ws = k["working_set_bytes"]

        # Determine cache level from working-set size
        cache_level = hierarchy[-1]["level"]
        level_bw = hierarchy[-1]["bandwidth_gbps"]
        for lvl in hierarchy:
            if "size_bytes" in lvl and ws <= lvl["size_bytes"]:
                cache_level = lvl["level"]
                level_bw = lvl["bandwidth_gbps"]
                break

        ridge = peak / level_bw
        bound = "memory" if ai < ridge else "compute"
        attainable = min(peak, ai * level_bw)
        efficiency = k["measured_gflops"] / attainable

        results.append({
            "name": k["name"],
            "arithmetic_intensity": round(ai, 6),
            "cache_level": cache_level,
            "bound": bound,
            "attainable_gflops": round(attainable, 4),
            "efficiency": round(efficiency, 4),
        })
    return results


# ---------------------------------------------------------------------------
# Gnuplot script generation
# ---------------------------------------------------------------------------

def generate_gnuplot_script(result, kernels_raw, output_gp, output_svg):
    """Generate a gnuplot script for the roofline chart."""
    peak = result["peak_gflops"]
    hierarchy = result["cache_hierarchy"]
    kernel_analysis = result["kernel_analysis"]

    # Map kernel names to measured GFLOP/s
    measured = {k["name"]: k["measured_gflops"] for k in kernels_raw}

    colors = {"L1": "#0000FF", "L2": "#008800", "L3": "#FF8800", "DRAM": "#880088"}

    lines = []
    lines.append(f'set terminal svg size 800,600 font "Arial,10" noenhanced')
    lines.append(f'set output "{output_svg}"')
    lines.append('')
    lines.append('set title "Hierarchical Roofline Model"')
    lines.append('set xlabel "Arithmetic Intensity (FLOP/Byte)"')
    lines.append('set ylabel "Performance (GFLOP/s)"')
    lines.append('')
    lines.append('set logscale xy 2')
    lines.append('set xrange [0.01:128]')
    lines.append('set yrange [0.1:256]')
    lines.append('set grid')
    lines.append('set key top left')
    lines.append('')

    # Compute ceiling: horizontal line at peak
    lines.append(f'# Peak compute ceiling')
    lines.append(f'set arrow from 0.01,{peak} to 128,{peak} nohead '
                 f'lc rgb "red" lw 2 dt 2')
    lines.append(f'set label "Peak Compute ({peak:.1f} GFLOP/s)" '
                 f'at 32,{peak * 1.15} tc rgb "red" font ",9"')
    lines.append('')

    # Memory bandwidth ceilings: P = AI * BW, up to the ridge point
    for h in hierarchy:
        lvl = h["level"]
        bw = h["bandwidth_gbps"]
        ridge = h["ridge_point"]
        color = colors.get(lvl, "#000000")

        # Diagonal line from left edge to ridge point
        ai_min = 0.01
        p_at_min = ai_min * bw
        lines.append(f'# {lvl} ceiling ({bw:.1f} GB/s)')
        lines.append(f'set arrow from {ai_min},{p_at_min} to {ridge},{peak} '
                     f'nohead lc rgb "{color}" lw 2')
        # Label
        label_ai = max(ai_min * 4, ridge * 0.3)
        label_p = label_ai * bw * 1.3
        lines.append(f'set label "{lvl} ({bw:.1f} GB/s)" '
                     f'at {label_ai:.4f},{label_p:.4f} tc rgb "{color}" '
                     f'font ",8" rotate by 45')

        # Ridge point marker
        lines.append(f'set arrow from {ridge},{peak * 0.05} to {ridge},{peak} '
                     f'nohead lc rgb "{color}" lw 1 dt 3')
        lines.append('')

    # Kernel data points (inline data)
    lines.append('# Kernel data points')
    for ka in kernel_analysis:
        name = ka["name"]
        ai = ka["arithmetic_intensity"]
        m_gf = measured.get(name, 0)
        lines.append(f'set label "{name}" at {ai * 1.2},{m_gf * 1.15} '
                     f'font ",7" tc rgb "#333333"')

    lines.append('')
    lines.append("plot '-' using 1:2 with points pt 7 ps 1.5 lc rgb 'black' "
                 "title 'Kernels'")
    for ka in kernel_analysis:
        name = ka["name"]
        ai = ka["arithmetic_intensity"]
        m_gf = measured.get(name, 0)
        lines.append(f'{ai} {m_gf}')
    lines.append('e')

    with open(output_gp, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ert_dir      = "/app/data/ert_raw"
    stream_file  = "/app/data/stream_results.txt"
    kernels_file = "/app/data/kernels.json"
    output_file  = "/app/results/roofline_analysis.json"
    output_gp    = "/app/results/roofline.gp"
    output_svg   = "/app/results/roofline_chart.svg"

    # 1. Peak GFLOP/s from high-FLOP data
    peak = extract_peak_gflops(ert_dir)

    # 2. Bandwidth profile from lowest-FLOP data
    lowest_flop = float("inf")
    lowest_file = None
    for fname in os.listdir(ert_dir):
        if fname.startswith("flop_") and fname.endswith(".dat"):
            flop = int(fname.split("_")[1].split(".")[0])
            if flop < lowest_flop:
                lowest_flop = flop
                lowest_file = fname

    data = parse_ert_file(os.path.join(ert_dir, lowest_file))
    metrics = compute_bandwidth_and_gflops(data)
    ws_arr, bw_arr = extract_max_bandwidth_per_ws(metrics)

    # 3. Detect cache hierarchy
    hierarchy = detect_cache_levels(ws_arr, bw_arr)
    for lvl in hierarchy:
        lvl["ridge_point"] = round(peak / lvl["bandwidth_gbps"], 4)

    # 4. STREAM corrections
    stream_raw = parse_stream(stream_file)
    stream_corrected = correct_stream(stream_raw)

    # 5. Kernel classification
    with open(kernels_file) as f:
        kernels = json.load(f)
    kernel_analysis = classify_kernels(kernels, hierarchy, peak)

    # 6. Write JSON output
    result = {
        "peak_gflops": peak,
        "cache_hierarchy": hierarchy,
        "stream_corrected": stream_corrected,
        "kernel_analysis": kernel_analysis,
    }
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Roofline analysis written to {output_file}")

    # 7. Generate gnuplot script
    generate_gnuplot_script(result, kernels, output_gp, output_svg)
    print(f"Gnuplot script written to {output_gp}")


if __name__ == "__main__":
    main()
