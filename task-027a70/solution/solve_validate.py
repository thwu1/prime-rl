#!/usr/bin/env python3
"""
Generate validation_report.json by running the C frequency response analyzer
on each filter specification.

"""
import subprocess
import json
import os
import sys


def parse_freqresp_line(output):
    """Parse a single non-comment line from freqresp output."""
    lines = [l for l in output.strip().split('\n') if l.strip() and not l.startswith('#')]
    if not lines:
        return None, None, None
    parts = lines[0].split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def main():
    specs = json.load(open('/app/filter_specs.json'))
    filters = []

    for spec in specs:
        N, Rp, Rs = spec['N'], spec['Rp'], spec['Rs']
        zpk_file = '/app/zpk_N%d_Rp%.1f_Rs%.1f.txt' % (N, Rp, Rs)

        if not os.path.isfile(zpk_file):
            print(f"WARNING: {zpk_file} not found, skipping", file=sys.stderr)
            continue

        # Read ZPK header for counts
        with open(zpk_file) as f:
            parts = f.readline().split()
            nz, np_count = int(parts[0]), int(parts[1])

        # Run freqresp at DC (w=0.01)
        res = subprocess.run(
            ['/app/freqresp', zpk_file, '0.01', '0.01', '1'],
            capture_output=True, text=True, timeout=10
        )
        _, _, dc_db = parse_freqresp_line(res.stdout)

        # Run freqresp at passband edge (w=1.0)
        res = subprocess.run(
            ['/app/freqresp', zpk_file, '1.0', '1.0', '1'],
            capture_output=True, text=True, timeout=10
        )
        _, _, pb_db = parse_freqresp_line(res.stdout)

        if dc_db is None or pb_db is None:
            print(f"ERROR: Could not parse freqresp output for N={N}", file=sys.stderr)
            continue

        filters.append({
            'N': N,
            'Rp': Rp,
            'Rs': Rs,
            'dc_gain_db': round(dc_db, 6),
            'passband_edge_db': round(pb_db, 6),
            'num_zeros': nz,
            'num_poles': np_count
        })

    report = {'filters': filters}
    with open('/app/validation_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Validation report written: {len(filters)} filters")
    for flt in filters:
        print(f"  N={flt['N']}, Rp={flt['Rp']}, Rs={flt['Rs']}: "
              f"DC={flt['dc_gain_db']:.2f}dB, PB_edge={flt['passband_edge_db']:.2f}dB")


if __name__ == '__main__':
    main()
