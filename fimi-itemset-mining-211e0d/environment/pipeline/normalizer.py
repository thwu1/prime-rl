#!/usr/bin/env python3
"""Dataset normalizer for FIMI-format transaction data.

Converts raw datasets to standard FIMI ASCII format:
  - One transaction per line
  - Space-separated non-negative integer item IDs
  - Items sorted ascending within each transaction
"""


import sys


def normalize_file(input_path, output_path):
    """Read a dataset and write it in standard FIMI format."""
    with open(input_path) as fin, open(output_path, 'w') as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            # Parse items as integers, skipping non-integer tokens
            items = []
            for token in line.split():
                try:
                    items.append(int(token))
                except ValueError:
                    continue
            if items:
                items = sorted(items)
                fout.write(' '.join(str(i) for i in items) + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input> <output>", file=sys.stderr)
        sys.exit(1)
    normalize_file(sys.argv[1], sys.argv[2])
