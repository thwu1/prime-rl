#!/usr/bin/env python3

"""Cross-validated hierarchical roofline performance analyzer.

Integrates ERT microbenchmark data, STREAM bandwidth measurements, and
theoretical hardware specifications to produce a validated roofline model
with gnuplot visualization.
"""

import json
import os
import math
import subprocess


def parse_ert_file(filepath):
    """Parse a single ERT raw data file, returning measurement points."""
    points = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            ws_bytes = int(parts[0])
            microseconds = float(parts[2])
            total_bytes = int(parts[3])
            total_flops = int(parts[4])
            time_sec = microseconds * 1e-6
            gbs = total_bytes / time_sec / 1e9
            gflops = total_flops / time_sec / 1e9
            points.append({"ws_bytes": ws_bytes, "gbs": gbs, "gflops": gflops})
    return points


def median(values):
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def detect_bandwidth_plateaus(data_dir):
    """Detect cache-level bandwidth plateaus from low-intensity ERT data.

    Uses f=1 and f=2 data (always memory-bound) to build a bandwidth-vs-
    working-set-size curve, then detects three transitions via stride-based
    ratio analysis on median-smoothed bandwidth values.
    """
    bw_by_ws = {}
    for flops_val in [1, 2]:
        fpath = os.path.join(data_dir, "flops_{:03d}.dat".format(flops_val))
        if not os.path.exists(fpath):
            continue
        for dp in parse_ert_file(fpath):
            ws = dp["ws_bytes"]
            if ws not in bw_by_ws:
                bw_by_ws[ws] = []
            bw_by_ws[ws].append(dp["gbs"])

    sorted_ws = sorted(bw_by_ws.keys())
    avg_bw = [sum(bw_by_ws[ws]) / len(bw_by_ws[ws]) for ws in sorted_ws]
    n = len(avg_bw)

    # 3-point median smoothing
    smoothed = list(avg_bw)
    for i in range(1, n - 1):
        smoothed[i] = median([avg_bw[i - 1], avg_bw[i], avg_bw[i + 1]])

    # Find transitions via stride-based ratio analysis
    stride = 3
    ratio_list = []
    for i in range(stride, n):
        if smoothed[i - stride] > 0:
            ratio = smoothed[i] / smoothed[i - stride]
            ratio_list.append((ratio, i))

    ratio_list.sort(key=lambda x: x[0])

    transitions = []
    for ratio_val, idx in ratio_list:
        if ratio_val >= 0.75:
            break
        if all(abs(idx - t) > stride + 1 for t in transitions):
            transitions.append(idx)
        if len(transitions) == 3:
            break

    transitions.sort()

    # Compute cache boundaries as geometric mean at transition
    boundaries = []
    for idx in transitions:
        low_ws = sorted_ws[max(0, idx - stride)]
        high_ws = sorted_ws[idx]
        boundary = int(math.sqrt(float(low_ws) * float(high_ws)))
        boundaries.append(boundary)

    # Compute plateau bandwidths as median within each segment
    segments = [0] + transitions + [n]
    level_bws = []
    for seg_i in range(len(segments) - 1):
        start = segments[seg_i]
        end = segments[seg_i + 1]
        margin = 2
        inner_start = start + (margin if seg_i > 0 else 0)
        inner_end = end - (margin if seg_i < len(segments) - 2 else 0)
        if inner_start >= inner_end:
            inner_start = start
            inner_end = end
        segment_bws = smoothed[inner_start:inner_end]
        if segment_bws:
            level_bws.append(median(segment_bws))
        else:
            level_bws.append(smoothed[start])

    return boundaries, level_bws


def detect_peak_gflops(data_dir):
    """Detect peak GFLOP/s from high arithmetic-intensity ERT data.

    Uses 95th percentile of compute-bound measurements at high FLOP counts.
    """
    all_gflops = []
    for flops_val in [16, 32, 64]:
        fpath = os.path.join(data_dir, "flops_{:03d}.dat".format(flops_val))
        if not os.path.exists(fpath):
            continue
        for dp in parse_ert_file(fpath):
            all_gflops.append(dp["gflops"])

    if not all_gflops:
        return 0.0

    all_gflops.sort()
    idx_95 = min(int(0.95 * len(all_gflops)), len(all_gflops) - 1)
    return all_gflops[idx_95]


def parse_stream_output(filepath):
    """Parse STREAM benchmark output to extract bandwidth measurements (GB/s)."""
    results = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            for kernel in ["Copy", "Scale", "Add", "Triad"]:
                if line.startswith(kernel + ":"):
                    parts = line.split()
                    bw_mbs = float(parts[1])
                    results[kernel.lower()] = bw_mbs / 1000.0  # MB/s -> GB/s
    return results


def compute_theoretical_peaks(spec):
    """Compute theoretical peak GFLOP/s and DRAM bandwidth from system spec.

    Peak GFLOP/s = cores * clock_ghz * (simd_width / sizeof(double)) * FMA_mult
    DRAM BW = channels * freq_ghz * bus_width * 2 (DDR = double data rate)
    """
    simd_doubles = spec["simd_width_bytes"] / 8.0
    fma_mult = 2.0 if spec["fma_capable"] else 1.0
    peak_gflops = spec["cores"] * spec["clock_ghz"] * simd_doubles * fma_mult

    freq_ghz = spec["memory_frequency_mhz"] / 1000.0
    dram_bw = spec["memory_channels"] * freq_ghz * spec["memory_bus_width_bytes"] * 2

    return peak_gflops, dram_bw


def get_memory_level(ws_bytes, boundaries):
    levels = ["L1", "L2", "L3", "DRAM"]
    for i, boundary in enumerate(boundaries):
        if ws_bytes <= boundary:
            return levels[i]
    return "DRAM"


def analyze_kernel(kernel, boundaries, level_bws, peak_gflops):
    level_names = ["L1", "L2", "L3", "DRAM"]
    flops = kernel["flops_per_element"]
    bytes_read = kernel["bytes_read_per_element"]
    bytes_written = kernel["bytes_written_per_element"]
    write_allocate = kernel["write_allocate"]
    ws_bytes = kernel["working_set_bytes"]

    total_bytes_no_wa = bytes_read + bytes_written
    ai = flops / total_bytes_no_wa

    if write_allocate:
        total_bytes_wa = bytes_read + 2 * bytes_written
        ai_wa = flops / total_bytes_wa
    else:
        ai_wa = None

    effective_ai = ai_wa if write_allocate else ai

    level = get_memory_level(ws_bytes, boundaries)
    level_idx = level_names.index(level)
    bw = level_bws[level_idx]

    ridge = peak_gflops / bw

    if effective_ai >= ridge:
        classification = "compute-bound"
        achievable = peak_gflops
    else:
        classification = "memory-bound"
        achievable = effective_ai * bw

    return {
        "name": kernel["name"],
        "arithmetic_intensity": round(ai, 6),
        "arithmetic_intensity_with_wa": round(ai_wa, 6) if ai_wa is not None else None,
        "memory_level": level,
        "classification": classification,
        "achievable_gflops": round(achievable, 4),
    }


def generate_gnuplot_chart(result, output_dir):
    """Generate gnuplot script and data files for roofline chart."""
    bws = result["empirical"]["bandwidths_gbs"]
    peak = result["empirical"]["peak_gflops"]
    theo_peak = result["theoretical"]["peak_gflops"]
    kernels = result["kernel_analysis"]

    # Write kernel operating points data file
    dat_path = os.path.join(output_dir, "kernel_points.dat")
    with open(dat_path, "w") as f:
        for k in kernels:
            effective_ai = k.get("arithmetic_intensity_with_wa")
            if effective_ai is None:
                effective_ai = k["arithmetic_intensity"]
            f.write("{:.6f} {:.4f} {}\n".format(
                effective_ai, k["achievable_gflops"], k["name"]))

    # Write gnuplot script
    gp_path = os.path.join(output_dir, "roofline.gp")
    svg_path = os.path.join(output_dir, "roofline.svg")

    script = []
    script.append("set terminal svg size 1000 700 enhanced font 'Helvetica,12'")
    script.append("set output '{}'".format(svg_path))
    script.append("")
    script.append("set logscale x 2")
    script.append("set logscale y 2")
    script.append("set xlabel 'Arithmetic Intensity (FLOP/byte)'")
    script.append("set ylabel 'Performance (GFLOP/s)'")
    script.append("set title 'Hierarchical Roofline Model'")
    script.append("set key top left")
    script.append("")
    script.append("set xrange [0.01:100]")
    script.append("set yrange [0.1:1000]")
    script.append("set grid")
    script.append("")
    script.append("l1_bw = {}".format(bws["L1"]))
    script.append("l2_bw = {}".format(bws["L2"]))
    script.append("l3_bw = {}".format(bws["L3"]))
    script.append("dram_bw = {}".format(bws["DRAM"]))
    script.append("peak = {}".format(peak))
    script.append("theo_peak = {}".format(theo_peak))
    script.append("")
    script.append("l1_roof(x) = (x * l1_bw < peak) ? x * l1_bw : peak")
    script.append("l2_roof(x) = (x * l2_bw < peak) ? x * l2_bw : peak")
    script.append("l3_roof(x) = (x * l3_bw < peak) ? x * l3_bw : peak")
    script.append("dram_roof(x) = (x * dram_bw < peak) ? x * dram_bw : peak")
    script.append("")
    script.append(
        "plot l1_roof(x) lw 2 lc rgb '#e41a1c' "
        "title 'L1 ({:.0f} GB/s)', \\".format(bws["L1"])
    )
    script.append(
        "     l2_roof(x) lw 2 lc rgb '#377eb8' "
        "title 'L2 ({:.0f} GB/s)', \\".format(bws["L2"])
    )
    script.append(
        "     l3_roof(x) lw 2 lc rgb '#4daf4a' "
        "title 'L3 ({:.0f} GB/s)', \\".format(bws["L3"])
    )
    script.append(
        "     dram_roof(x) lw 2 lc rgb '#ff7f00' "
        "title 'DRAM ({:.0f} GB/s)', \\".format(bws["DRAM"])
    )
    script.append(
        "     theo_peak lw 1 dt 2 lc rgb '#999999' "
        "title 'Theoretical Peak ({:.1f} GFLOP/s)', \\".format(theo_peak)
    )
    script.append(
        "     '{}' using 1:2 with points pt 7 ps 2 "
        "lc rgb '#000000' title 'Kernels', \\".format(dat_path)
    )
    script.append(
        "     '{}' using 1:2:3 with labels offset 1.5,1 "
        "font ',9' notitle".format(dat_path)
    )

    with open(gp_path, "w") as f:
        f.write("\n".join(script) + "\n")

    return gp_path


def main():
    data_dir = "/app/data"
    kernels_file = "/app/kernels.json"
    stream_file = "/app/stream_output.txt"
    spec_file = "/app/system_spec.json"
    output_file = "/app/results/roofline_analysis.json"
    output_dir = "/app/results"

    os.makedirs(output_dir, exist_ok=True)

    # Load inputs
    with open(kernels_file) as f:
        kernels = json.load(f)["kernels"]
    with open(spec_file) as f:
        spec = json.load(f)

    # 1. Detect cache levels and bandwidths from ERT data
    boundaries, level_bws = detect_bandwidth_plateaus(data_dir)
    peak_gflops = detect_peak_gflops(data_dir)

    # 2. Parse STREAM output
    stream_bws = parse_stream_output(stream_file)

    # 3. Compute theoretical peaks
    theo_peak, theo_dram_bw = compute_theoretical_peaks(spec)

    # 4. Cross-validation
    # STREAM Triad: counts 24 bytes/element (2 reads + 1 write), but actual
    # hardware traffic is 32 bytes/element due to write-allocate on the
    # destination array (fetches cache line before overwrite). ERT's
    # read-modify-write kernel has no write-allocate, so ERT reports the
    # true hardware throughput directly. To compare:
    #   corrected_stream = reported * (32/24) = reported * 4/3
    stream_triad_corrected = stream_bws["triad"] * (32.0 / 24.0)

    dram_bw_ert = level_bws[3]  # DRAM is index 3
    peak_efficiency = peak_gflops / theo_peak
    dram_efficiency = dram_bw_ert / theo_dram_bw
    stream_ert_ratio = stream_triad_corrected / dram_bw_ert

    # 5. Build output
    level_names = ["L1", "L2", "L3", "DRAM"]
    bandwidths = {}
    ridge_points = {}
    cache_bounds = {}
    for i, name in enumerate(level_names):
        bandwidths[name] = round(level_bws[i], 2)
        ridge_points[name] = round(peak_gflops / level_bws[i], 6)
        if i < 3:
            cache_bounds[name] = boundaries[i]

    kernel_results = [
        analyze_kernel(k, boundaries, level_bws, peak_gflops) for k in kernels
    ]

    result = {
        "empirical": {
            "bandwidths_gbs": bandwidths,
            "cache_boundaries_bytes": cache_bounds,
            "peak_gflops": round(peak_gflops, 2),
        },
        "theoretical": {
            "peak_gflops": round(theo_peak, 2),
            "dram_bandwidth_gbs": round(theo_dram_bw, 2),
        },
        "stream": {
            "copy_gbs": round(stream_bws["copy"], 4),
            "scale_gbs": round(stream_bws["scale"], 4),
            "add_gbs": round(stream_bws["add"], 4),
            "triad_gbs": round(stream_bws["triad"], 4),
        },
        "validation": {
            "peak_efficiency": round(peak_efficiency, 4),
            "dram_efficiency": round(dram_efficiency, 4),
            "stream_triad_corrected_gbs": round(stream_triad_corrected, 4),
            "stream_ert_ratio": round(stream_ert_ratio, 4),
        },
        "ridge_points": ridge_points,
        "kernel_analysis": kernel_results,
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    # 6. Generate gnuplot roofline chart
    gp_path = generate_gnuplot_chart(result, output_dir)
    subprocess.run(["gnuplot", gp_path], check=True)

    print("Roofline analysis written to {}".format(output_file))
    print("Roofline chart written to {}".format(
        os.path.join(output_dir, "roofline.svg")))


if __name__ == "__main__":
    main()
