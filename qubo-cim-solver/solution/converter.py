#!/usr/bin/env python3
"""Convert text-format Ising/QUBO instances to JSON.

Replaces the buggy Rust converter which had:
  1. Type mismatch: usize indices pushed into [f64;3] array without cast
  2. Case mismatch: output "Ising"/"QUBO" but solver expects "ising"/"qubo"
"""
import json
import os
import sys


def parse_ising(content):
    """Parse text-format Ising instance (N/J/H lines) to dict."""
    n = 0
    couplings = []
    fields = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if parts[0] == 'N':
            n = int(parts[1])
            fields = [0.0] * n
        elif parts[0] == 'J':
            i, j = int(parts[1]), int(parts[2])
            val = float(parts[3])
            couplings.append([i, j, val])
        elif parts[0] == 'H':
            i = int(parts[1])
            val = float(parts[2])
            fields[i] = val
    return {"type": "ising", "n": n, "couplings": couplings, "fields": fields}


def parse_qubo(content):
    """Parse text-format QUBO instance (N/Q lines) to dict."""
    n = 0
    Q = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if parts[0] == 'N':
            n = int(parts[1])
            Q = [[0.0] * n for _ in range(n)]
        elif parts[0] == 'Q':
            i, j = int(parts[1]), int(parts[2])
            val = float(parts[3])
            Q[i][j] = val
    return {"type": "qubo", "n": n, "Q": Q}


def main():
    if len(sys.argv) < 3:
        print("Usage: converter.py <input_dir> <output_dir>")
        sys.exit(1)

    input_dir, output_dir = sys.argv[1], sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)

    for fname in sorted(os.listdir(input_dir)):
        path = os.path.join(input_dir, fname)
        if os.path.isdir(path):
            continue
        name, ext = os.path.splitext(fname)
        if ext not in ('.ising', '.qubo'):
            continue

        with open(path) as f:
            content = f.read()

        if ext == '.ising':
            instance = parse_ising(content)
        else:
            instance = parse_qubo(content)

        output_path = os.path.join(output_dir, f"{name}.json")
        with open(output_path, 'w') as f:
            json.dump(instance, f, indent=2)
        print(f"Converted {path} -> {output_path}")


if __name__ == "__main__":
    main()
