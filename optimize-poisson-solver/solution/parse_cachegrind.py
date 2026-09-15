#!/usr/bin/env python3
"""Parse valgrind cachegrind summary output and write profile_report.txt."""
import sys
import re


def parse_cachegrind(input_file, output_file):
    with open(input_file) as f:
        text = f.read()

    # Extract D1 miss rate (overall percentage)
    m = re.search(r"D1\s+miss rate:\s+([\d.]+)%", text)
    d1_miss = float(m.group(1)) if m else 0.0

    # Extract LLd miss rate (last-level data cache miss rate)
    m = re.search(r"LLd\s+miss rate:\s+([\d.]+)%", text)
    dl_miss = float(m.group(1)) if m else 0.0

    # Extract total instruction references
    m = re.search(r"I\s+refs:\s+([\d,]+)", text)
    total_instr = int(m.group(1).replace(",", "")) if m else 0

    with open(output_file, "w") as f:
        f.write(f"D1_miss_rate={d1_miss}\n")
        f.write(f"DLmiss_rate={dl_miss}\n")
        f.write(f"total_instructions={total_instr}\n")


if __name__ == "__main__":
    parse_cachegrind(sys.argv[1], sys.argv[2])
