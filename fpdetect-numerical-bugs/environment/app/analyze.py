#!/usr/bin/env python3
"""CLI entry point for the floating-point anomaly detector."""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fpdetect.analyzer import run_analysis


def main():
    parser = argparse.ArgumentParser(
        description='Floating-point numerical anomaly detector'
    )
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--iterations', type=int, default=200,
                        help='Fuzzing iterations per function')
    parser.add_argument('--functions', type=str, default=None,
                        help='Path to functions config file')
    parser.add_argument('--output', type=str, default='/app/report.json',
                        help='Output report path')
    args = parser.parse_args()

    if args.functions and os.path.exists(args.functions):
        with open(args.functions) as f:
            functions = [line.strip() for line in f
                         if line.strip() and not line.startswith('#')]
    else:
        functions = ['exp', 'log', 'sin', 'cos', 'cosh', 'sinh',
                      'tanh', 'erf', 'lgamma']

    results = run_analysis(functions, iterations=args.iterations, seed=args.seed)

    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Report written to {args.output}")
    print(f"Functions analyzed: {len(results)}")
    for fname, data in results.items():
        print(f"  {fname}: {data['total_anomalies']} anomalies")


if __name__ == '__main__':
    main()
