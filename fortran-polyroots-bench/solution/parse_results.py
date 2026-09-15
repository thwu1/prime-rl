#!/usr/bin/env python3
"""Parse Fortran benchmark output files and generate /app/results.json."""

import json
import sys


def parse_output_file(path):
    """Parse a single Fortran output file into a structured dict."""
    methods = {}

    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue

            if parts[0] == 'METHOD':
                name = parts[1]
                if parts[2] == 'FAILED':
                    methods[name] = {
                        'max_backward_error': None,
                        'roots': [],
                        'status': int(parts[3])
                    }
                else:
                    berr = float(parts[2])
                    status = int(parts[3])
                    if name not in methods:
                        methods[name] = {
                            'max_backward_error': berr,
                            'roots': [],
                            'status': status
                        }
                    else:
                        methods[name]['max_backward_error'] = berr
                        methods[name]['status'] = status

            elif parts[0] == 'ROOT':
                name = parts[1]
                re_val = float(parts[3])
                im_val = float(parts[4])
                if name not in methods:
                    methods[name] = {
                        'max_backward_error': None,
                        'roots': [],
                        'status': 0
                    }
                methods[name]['roots'].append({'real': re_val, 'imag': im_val})

    # Sort roots by real part ascending, then imaginary part ascending.
    # Use rounded real part (6 decimal places) as primary key to group
    # conjugate pairs whose real parts differ only by floating-point noise.
    # The distinct real-part clusters for this polynomial are ~0.17 apart,
    # so 1e-6 granularity safely groups conjugates without merging clusters.
    for name in methods:
        methods[name]['roots'].sort(key=lambda r: (round(r['real'], 6), r['imag']))

    # Find best method (smallest max backward error among successful methods)
    best_method = None
    best_berr = float('inf')
    for name, data in methods.items():
        if data['status'] == 0 and data['max_backward_error'] is not None:
            if data['max_backward_error'] < best_berr:
                best_berr = data['max_backward_error']
                best_method = name

    return {
        'methods': methods,
        'best_method': best_method
    }


def main():
    r64_file = '/tmp/output_r64.txt'
    r128_file = '/tmp/output_r128.txt'
    output_file = '/app/results.json'

    r64_results = parse_output_file(r64_file)
    r128_results = parse_output_file(r128_file)

    combined = {
        'real64': r64_results,
        'real128': r128_results
    }

    with open(output_file, 'w') as f:
        json.dump(combined, f, indent=2)

    print(f'Results written to {output_file}')
    print(f'real64 best: {r64_results["best_method"]}')
    print(f'real128 best: {r128_results["best_method"]}')


if __name__ == '__main__':
    main()
