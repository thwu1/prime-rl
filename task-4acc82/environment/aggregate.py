#!/usr/bin/env python3
"""Aggregate error entries from joined CSV into summary statistics."""
import csv
import sys
from collections import defaultdict


def aggregate(input_path, output_path):
    stats = {}
    with open(input_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['error_code'].strip().upper()
            if code not in stats:
                stats[code] = {
                    'category': row['category'],
                    'severity': row['severity'],
                    'count': 0,
                    'messages': [],
                }
            stats[code]['count'] += 1
            msg = row.get('message', '').strip()
            if msg:
                stats[code]['messages'].append(msg)

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'error_code', 'category', 'severity', 'count', 'first_message'
        ])
        for code in sorted(stats.keys()):
            s = stats[code]
            first_msg = sorted(set(s['messages']))[0] if s['messages'] else ''
            writer.writerow([
                code, s['category'], s['severity'], s['count'], first_msg
            ])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.csv> <output.csv>", file=sys.stderr)
        sys.exit(1)
    aggregate(sys.argv[1], sys.argv[2])
