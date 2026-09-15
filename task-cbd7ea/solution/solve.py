#!/usr/bin/env python3
"""
Hierarchical Roofline Model Construction

Processes raw ERT measurements, STREAM benchmark output, and hwloc cache
topology to build a complete hierarchical roofline model, classify
application kernels, and generate a gnuplot roofline visualization.

"""

import argparse
import json
import os
import re


def parse_ert_config(path):
    """Parse ERT configuration file for measurement parameters."""
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                config[parts[0]] = parts[1].strip()
            elif len(parts) == 1:
                config[parts[0]] = ''
    return config


def get_bytes_per_element(config):
    """Determine bytes per element from ERT precision config."""
    precision = config.get('ERT_PRECISION', 'FP64')
    if precision == 'FP64':
        return 8
    elif precision == 'FP32':
        return 4
    else:
        return 8


def parse_ert_bandwidth(path):
    """Parse raw ERT bandwidth sweep data (GnuPlot tab-separated format)."""
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                ws_elements = int(parts[0])
                trial = int(parts[1])
                bandwidth = float(parts[2])
                data.append((ws_elements, trial, bandwidth))
    return data


def parse_ert_compute(path):
    """Parse raw ERT compute sweep data (GnuPlot tab-separated format)."""
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                fpe = int(parts[0])
                trial = int(parts[1])
                gflops = float(parts[2])
                data.append((fpe, trial, gflops))
    return data


def parse_stream_output(path):
    """Parse STREAM benchmark text output for Best Rate MB/s values."""
    results = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^(Copy|Scale|Add|Triad):\s+([\d.]+)', line)
            if m:
                results[m.group(1)] = float(m.group(2))
    return results


def compute_peak_bandwidths(bw_data, cache_sizes, bytes_per_element):
    """
    Classify ERT bandwidth measurements into cache levels and extract peaks.

    Working set classification uses per-core cache sizes:
    - L1: ws_bytes < L1_size
    - L2: L1_size <= ws_bytes < L2_size
    - L3: L2_size <= ws_bytes < L3_size
    - DRAM: ws_bytes >= L3_size
    """
    l1_size = cache_sizes['L1']
    l2_size = cache_sizes['L2']
    l3_size = cache_sizes['L3']

    levels = {'L1': [], 'L2': [], 'L3': [], 'DRAM': []}

    for ws_elements, trial, bw in bw_data:
        ws_bytes = ws_elements * bytes_per_element
        if ws_bytes < l1_size:
            levels['L1'].append(bw)
        elif ws_bytes < l2_size:
            levels['L2'].append(bw)
        elif ws_bytes < l3_size:
            levels['L3'].append(bw)
        else:
            levels['DRAM'].append(bw)

    peak_bw = {}
    for level, values in levels.items():
        if values:
            peak_bw[level] = max(values)
        else:
            raise ValueError(f"No bandwidth measurements for {level}")

    return peak_bw


def compute_peak_gflops(compute_data):
    """Extract empirical peak GFLOP/s as maximum across all measurements."""
    return max(gf for _, _, gf in compute_data)


def compute_stream_corrections(stream_results):
    """
    Correct STREAM bandwidth for write-allocate cache behavior.

    From stream.c kernel definitions and bytes[] array:
    - Copy:  c[i] = a[i]           -> bytes[] counts 2*8=16B, hardware: 3*8=24B -> 1.5
    - Scale: b[i] = scalar*c[i]    -> same as Copy -> 1.5
    - Add:   c[i] = a[i]+b[i]      -> bytes[] counts 3*8=24B, hardware: 4*8=32B -> 4/3
    - Triad: a[i] = b[i]+s*c[i]    -> same as Add -> 4/3
    """
    wa_factors = {
        'Copy': 1.5,
        'Scale': 1.5,
        'Add': 4.0 / 3.0,
        'Triad': 4.0 / 3.0,
    }

    corrected = {}
    for kernel_name, reported_mb_s in stream_results.items():
        factor = wa_factors[kernel_name]
        corrected_gb_s = reported_mb_s * factor / 1000.0
        corrected[kernel_name] = {
            'reported_mb_per_s': reported_mb_s,
            'corrected_gb_per_s': corrected_gb_s,
            'wa_factor': factor,
        }

    return corrected


def analyze_kernels(kernels, peak_gflops, peak_bandwidths):
    """
    For each kernel at each memory level, compute arithmetic intensity,
    classify as compute-bound or memory-bound, and determine attainable
    performance using the roofline model.
    """
    results = []

    for kernel in kernels:
        levels_analysis = {}

        for level in ['L1', 'L2', 'L3', 'DRAM']:
            bw = peak_bandwidths[level]
            ridge_point = peak_gflops / bw
            bytes_at_level = kernel['bytes_per_level'][level]
            ai = kernel['total_flops'] / bytes_at_level

            if ai >= ridge_point:
                bound = 'compute'
                attainable = peak_gflops
            else:
                bound = 'memory'
                attainable = ai * bw

            levels_analysis[level] = {
                'arithmetic_intensity': ai,
                'bound': bound,
                'attainable_gflops': attainable,
            }

        results.append({
            'name': kernel['name'],
            'total_flops': kernel['total_flops'],
            'levels': levels_analysis,
        })

    return results


def generate_gnuplot_script(svg_path, gp_path, peak_gflops, peak_bandwidths, kernel_analysis):
    """Generate a gnuplot script for the hierarchical roofline chart."""
    lines = []
    # Use noenhanced so underscores in kernel names appear literally in SVG
    lines.append('set terminal svg noenhanced size 1000,700 font "Arial,12"')
    lines.append(f'set output "{svg_path}"')
    lines.append('set title "Hierarchical Roofline Model"')
    lines.append('set xlabel "Arithmetic Intensity (FLOP/byte)"')
    lines.append('set ylabel "Attainable Performance (GFLOP/s)"')
    lines.append('set logscale x 2')
    lines.append('set logscale y 2')
    lines.append('set xrange [0.01:512]')
    lines.append('set yrange [0.5:128]')
    lines.append('set key top left')
    lines.append('set grid')
    lines.append('')

    # Define constants
    lines.append(f'peak = {peak_gflops}')
    for level in ['L1', 'L2', 'L3', 'DRAM']:
        bw = peak_bandwidths[level]
        lines.append(f'bw_{level.lower()} = {bw}')
    lines.append('')

    # Roofline functions: min(peak, bw*x)
    for level in ['L1', 'L2', 'L3', 'DRAM']:
        lname = level.lower()
        lines.append(f'f_{lname}(x) = x < peak/bw_{lname} ? bw_{lname}*x : peak')
    lines.append('')

    # Cache level labels positioned along their bandwidth lines
    label_x = {'L1': 0.014, 'L2': 0.05, 'L3': 0.18, 'DRAM': 0.5}
    for level in ['L1', 'L2', 'L3', 'DRAM']:
        bw = peak_bandwidths[level]
        x = label_x[level]
        y = bw * x
        lines.append(f'set label "{level} ({bw:.1f} GB/s)" at {x},{y*1.3} font ",9"')

    # Peak compute label
    lines.append(f'set label "Peak ({peak_gflops} GFLOP/s)" at 16,{peak_gflops * 1.15} font ",9"')
    lines.append('')

    # Kernel operating points at DRAM level
    for kernel in kernel_analysis:
        name = kernel['name']
        ai = kernel['levels']['DRAM']['arithmetic_intensity']
        att = kernel['levels']['DRAM']['attainable_gflops']
        lines.append(f'set label "{name}" at {ai},{att} point pt 7 ps 1.5 offset char 1,0.5')
    lines.append('')

    # Plot roofline functions
    colors = {'l1': '#0000FF', 'l2': '#00AA00', 'l3': '#FF8800', 'dram': '#FF0000'}
    plot_parts = []
    for level in ['L1', 'L2', 'L3', 'DRAM']:
        lname = level.lower()
        color = colors[lname]
        plot_parts.append(f'f_{lname}(x) title "{level}" with lines lw 2 lc rgb "{color}"')

    lines.append('plot ' + ', \\\n     '.join(plot_parts))

    with open(gp_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Build hierarchical roofline model')
    parser.add_argument('--l1-size', type=int, required=True, help='L1 data cache size in bytes')
    parser.add_argument('--l2-size', type=int, required=True, help='L2 cache size in bytes')
    parser.add_argument('--l3-size', type=int, required=True, help='L3 cache size in bytes')
    args = parser.parse_args()

    data_dir = '/app/data'
    output_path = '/app/results/roofline_analysis.json'
    svg_path = '/app/results/roofline_chart.svg'
    gp_path = '/app/results/roofline.gp'

    cache_sizes = {
        'L1': args.l1_size,
        'L2': args.l2_size,
        'L3': args.l3_size,
    }

    # Parse ERT configuration for precision info
    ert_config = parse_ert_config(os.path.join(data_dir, 'ert.conf'))
    bytes_per_element = get_bytes_per_element(ert_config)

    # Parse raw ERT bandwidth sweep data
    bw_data = parse_ert_bandwidth(os.path.join(data_dir, 'ert_bandwidth.dat'))

    # Parse raw ERT compute sweep data
    compute_data = parse_ert_compute(os.path.join(data_dir, 'ert_compute.dat'))

    # Parse STREAM benchmark output
    stream_results = parse_stream_output(os.path.join(data_dir, 'stream_output.txt'))

    # Load application kernels
    with open(os.path.join(data_dir, 'kernels.json')) as f:
        kernels = json.load(f)

    # Build roofline model
    peak_gflops = compute_peak_gflops(compute_data)
    peak_bandwidths = compute_peak_bandwidths(bw_data, cache_sizes, bytes_per_element)

    # Construct memory level characterization with ridge points
    memory_levels = {}
    for level in ['L1', 'L2', 'L3', 'DRAM']:
        bw = peak_bandwidths[level]
        memory_levels[level] = {
            'peak_bandwidth_gb_per_s': bw,
            'ridge_point_flop_per_byte': peak_gflops / bw,
        }

    # STREAM write-allocate correction
    stream_corrected = compute_stream_corrections(stream_results)

    # Kernel analysis
    kernel_analysis = analyze_kernels(kernels, peak_gflops, peak_bandwidths)

    # Assemble and write JSON output
    output = {
        'empirical_peak_gflops': peak_gflops,
        'memory_levels': memory_levels,
        'stream_corrected': stream_corrected,
        'kernel_analysis': kernel_analysis,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Roofline analysis written to {output_path}")

    # Generate gnuplot script for roofline chart
    generate_gnuplot_script(svg_path, gp_path, peak_gflops, peak_bandwidths, kernel_analysis)
    print(f"Gnuplot script written to {gp_path}")


if __name__ == '__main__':
    main()
