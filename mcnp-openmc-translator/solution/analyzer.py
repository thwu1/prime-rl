#!/usr/bin/env python3
"""ICSBEP benchmark validation analysis — statistical analysis of uncertainties dataset."""

import json
import math
import os
import sys
from collections import defaultdict

from scipy.stats import norm


def parse_benchmark_name(name):
    """Extract fissile material, physical form, and neutron spectrum from ICSBEP name.

    Naming convention: <fissile>-<form>-<spectrum>-<number>
    where fissile may be multi-part (e.g. 'u233').
    """
    parts = name.strip().split('-')

    # Handle u233 (two-part fissile identifier)
    if parts[0] == 'u233':
        fissile = 'u233'
        form = parts[1]
        spectrum = parts[2]
    else:
        fissile = parts[0]
        form = parts[1]
        spectrum = parts[2]

    category = f"{fissile}-{form}-{spectrum}"
    return fissile, form, spectrum, category


def compute_weighted_mean(entries):
    """Compute weighted mean keff (weighted by 1/sigma^2), skipping zero uncertainty."""
    valid = [e for e in entries if e['uncertainty'] > 0]
    if not valid:
        return sum(e['keff'] for e in entries) / len(entries)
    weights = [1.0 / (e['uncertainty'] ** 2) for e in valid]
    w_sum = sum(weights)
    return sum(w * e['keff'] for w, e in zip(weights, valid)) / w_sum


def compute_chi_squared(entries):
    """Compute chi-squared against unity: sum((keff - 1.0)^2 / sigma^2)."""
    valid = [e for e in entries if e['uncertainty'] > 0]
    if not valid:
        return 0.0
    return sum(((e['keff'] - 1.0) / e['uncertainty']) ** 2 for e in valid)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <uncertainties.csv> <output.json>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    # Parse CSV
    entries = []
    with open(input_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 4:
                continue

            benchmark = parts[0]
            case = parts[1]
            keff = float(parts[2])
            uncertainty = float(parts[3])

            fissile, form, spectrum, category = parse_benchmark_name(benchmark)

            entries.append({
                'benchmark': benchmark,
                'case': case,
                'keff': keff,
                'uncertainty': uncertainty,
                'fissile': fissile,
                'form': form,
                'spectrum': spectrum,
                'category': category,
            })

    total_entries = len(entries)
    unique_benchmarks = len(set(e['benchmark'] for e in entries))

    # ---- Per-category statistics ----
    cat_groups = defaultdict(list)
    for e in entries:
        cat_groups[e['category']].append(e)

    categories = {}
    for cat_name in sorted(cat_groups):
        cat_entries = cat_groups[cat_name]
        count = len(cat_entries)
        mean_keff = sum(e['keff'] for e in cat_entries) / count
        weighted_mean = compute_weighted_mean(cat_entries)
        chi_sq = compute_chi_squared(cat_entries)
        n_valid = len([e for e in cat_entries if e['uncertainty'] > 0])
        dof = max(n_valid - 1, 1)
        reduced_chi_sq = chi_sq / dof if n_valid > 0 else 0.0
        birge_ratio = math.sqrt(chi_sq / max(n_valid, 1)) if n_valid > 0 else 0.0

        categories[cat_name] = {
            'count': count,
            'mean_keff': round(mean_keff, 6),
            'weighted_mean_keff': round(weighted_mean, 6),
            'chi_squared': round(chi_sq, 4),
            'reduced_chi_squared': round(reduced_chi_sq, 4),
            'birge_ratio': round(birge_ratio, 4),
        }

    # ---- Per-fissile summary ----
    fissile_groups = defaultdict(list)
    for e in entries:
        fissile_groups[e['fissile']].append(e)

    fissile_summary = {}
    for fissile_name in sorted(fissile_groups):
        f_entries = fissile_groups[fissile_name]
        count = len(f_entries)
        mean_keff = sum(e['keff'] for e in f_entries) / count
        weighted_mean = compute_weighted_mean(f_entries)
        fissile_summary[fissile_name] = {
            'count': count,
            'mean_keff': round(mean_keff, 6),
            'weighted_mean_keff': round(weighted_mean, 6),
        }

    # ---- Outlier detection (Chauvenet's criterion) ----
    valid_entries = [e for e in entries if e['uncertainty'] > 0]
    n = len(valid_entries)

    # Chauvenet threshold: reject if P(|Z| > z) < 1/(2N)
    # z_crit = norm.ppf(1 - 1/(4N))
    z_crit = norm.ppf(1.0 - 1.0 / (4.0 * n))

    outliers = []
    for e in valid_entries:
        deviation = (e['keff'] - 1.0) / e['uncertainty']
        if abs(deviation) > z_crit:
            outliers.append({
                'benchmark': e['benchmark'],
                'case': e['case'],
                'keff': e['keff'],
                'uncertainty': e['uncertainty'],
                'deviation_sigma': round(deviation, 4),
            })

    outliers.sort(key=lambda x: abs(x['deviation_sigma']), reverse=True)

    # ---- Build report ----
    report = {
        'total_entries': total_entries,
        'total_benchmarks': unique_benchmarks,
        'categories': categories,
        'fissile_summary': fissile_summary,
        'outliers': outliers,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Analysis: {total_entries} entries, {unique_benchmarks} benchmarks, "
          f"{len(categories)} categories, {len(outliers)} outliers (z_crit={z_crit:.3f})")


if __name__ == '__main__':
    main()
