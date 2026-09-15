#!/usr/bin/env python3
"""Benchmark pipeline — reads QASM circuits, optimizes, and reports results.

Processes all .qasm files in /app/benchmarks/ and writes a JSON report
to /app/results/report.json.
"""

import sys
sys.path.insert(0, '/app')


def main():
    raise NotImplementedError("Implement the benchmark pipeline")


if __name__ == '__main__':
    main()
