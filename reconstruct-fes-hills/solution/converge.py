#!/usr/bin/env python3
"""Convergence analysis for metadynamics FES reconstruction.

Divides simulation time into cumulative windows, reconstructs FES for each,
and computes pairwise convergence metrics.

"""

import argparse
import json
import math
import os
import subprocess
import sys


def get_time_range(hills_file):
    """Extract first and last hill timestamps from a HILLS file."""
    times = []
    with open(hills_file) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            times.append(float(s.split()[0]))
    return min(times), max(times)


def count_hills_in_range(hills_file, tmin, tmax):
    """Count data rows in HILLS file with tmin <= time <= tmax."""
    count = 0
    with open(hills_file) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            t = float(s.split()[0])
            if tmin <= t <= tmax:
                count += 1
    return count


def run_preprocess(hills_file, tmin, tmax, output_file):
    """Invoke preprocess.awk to filter HILLS by time window."""
    result = subprocess.run(
        ['gawk', '-v', f'tmin={tmin}', '-v', f'tmax={tmax}',
         '-f', '/app/preprocess.awk', hills_file],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"preprocess.awk failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    with open(output_file, 'w') as f:
        f.write(result.stdout)


def run_sum_hills(hills_file, grid_min, grid_max, grid_bins, periodic, outfile):
    """Invoke sum_hills to reconstruct FES."""
    cmd = [
        'python3', '/app/sum_hills',
        '--hills', hills_file,
        f'--grid-min={grid_min}',
        f'--grid-max={grid_max}',
        f'--grid-bins={grid_bins}',
        f'--periodic={periodic}',
        '--outfile', outfile,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"sum_hills failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def parse_fes_values(filepath):
    """Extract FES values from a sum_hills output file."""
    vals = []
    with open(filepath) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            parts = s.split()
            ncols = len(parts)
            if ncols == 3:
                vals.append(float(parts[1]))
            elif ncols == 5:
                vals.append(float(parts[2]))
    return vals


def compute_metrics(fes_a, fes_b):
    """Compute RMSD and max absolute difference between two FES arrays."""
    n = len(fes_a)
    sum_sq = 0.0
    max_diff = 0.0
    for i in range(n):
        d = fes_a[i] - fes_b[i]
        sum_sq += d * d
        ad = abs(d)
        if ad > max_diff:
            max_diff = ad
    rmsd = math.sqrt(sum_sq / n)
    return rmsd, max_diff


def main():
    parser = argparse.ArgumentParser(description='FES convergence analysis')
    parser.add_argument('--hills', required=True)
    parser.add_argument('--grid-min', required=True)
    parser.add_argument('--grid-max', required=True)
    parser.add_argument('--grid-bins', required=True)
    parser.add_argument('--periodic', required=True)
    parser.add_argument('--windows', required=True, type=int)
    parser.add_argument('--outfile', required=True)
    args = parser.parse_args()

    t_first, t_last = get_time_range(args.hills)
    n_windows = args.windows
    window_width = (t_last - t_first) / n_windows

    windows_info = []
    fes_arrays = []

    for i in range(n_windows):
        t_end = t_first + (i + 1) * window_width
        t_start_cum = 0.0

        # Preprocess: extract all hills up to t_end
        window_hills = f'/app/_conv_window_{i}.dat'
        run_preprocess(args.hills, t_start_cum, t_end, window_hills)

        # Count hills in this cumulative range
        n_hills = count_hills_in_range(args.hills, t_start_cum, t_end)

        # Reconstruct FES
        window_fes = f'/app/_conv_fes_{i}.dat'
        run_sum_hills(window_hills, args.grid_min, args.grid_max,
                      args.grid_bins, args.periodic, window_fes)

        windows_info.append({
            'index': i,
            'time_end': t_end,
            'n_hills': n_hills,
        })
        fes_arrays.append(parse_fes_values(window_fes))

        # Clean up intermediate hills file
        os.remove(window_hills)

    # Compute pairwise metrics
    pairwise = []
    for i in range(len(fes_arrays) - 1):
        rmsd, max_diff = compute_metrics(fes_arrays[i], fes_arrays[i + 1])
        pairwise.append({
            'pair': [i, i + 1],
            'fes_rmsd': rmsd,
            'fes_max_diff': max_diff,
        })

    # Clean up intermediate FES files
    for i in range(n_windows):
        fes_file = f'/app/_conv_fes_{i}.dat'
        if os.path.exists(fes_file):
            os.remove(fes_file)

    result = {
        'n_windows': n_windows,
        'windows': windows_info,
        'pairwise_metrics': pairwise,
        'final_rmsd': pairwise[-1]['fes_rmsd'] if pairwise else 0.0,
    }

    with open(args.outfile, 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
