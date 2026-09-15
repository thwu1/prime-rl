#!/usr/bin/env python3
"""Parse a GLPK solution file (-o output) and write a schedule CSV."""

import sys
import csv
import re


def parse_instance(filepath):
    """Read OR-Library JSP instance to recover machine/duration data."""
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]
    tokens = lines[0].split()
    num_jobs = int(tokens[0])
    num_machines = int(tokens[1])
    jobs = []
    for j in range(num_jobs):
        parts = lines[1 + j].split()
        operations = []
        for k in range(num_machines):
            machine = int(parts[2 * k])
            duration = int(parts[2 * k + 1])
            operations.append((machine, duration))
        jobs.append(operations)
    return num_jobs, num_machines, jobs


def parse_glpk_output(sol_path):
    """Extract column (variable) values from a GLPK printable-output file."""
    variables = {}
    in_columns = False

    with open(sol_path) as f:
        for line in f:
            if "Column name" in line:
                in_columns = True
                continue
            if not in_columns:
                continue

            stripped = line.strip()
            if stripped.startswith("---"):
                continue
            if stripped == "":
                if variables:
                    break
                continue

            parts = stripped.split()
            if len(parts) < 4:
                continue

            # First field must be the row number
            try:
                int(parts[0])
            except ValueError:
                continue

            col_name = parts[1]

            # parts[2] is the status indicator (B, NL, NU, NF, *)
            # parts[3] is the activity (variable value)
            try:
                activity = float(parts[3])
            except (ValueError, IndexError):
                # Fallback: some GLPK versions omit status for MIP columns
                try:
                    activity = float(parts[2])
                except (ValueError, IndexError):
                    continue

            variables[col_name] = activity

    return variables


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <instance.txt> <solution.sol> <output.csv>")
        sys.exit(1)

    instance_path = sys.argv[1]
    sol_path = sys.argv[2]
    output_path = sys.argv[3]

    num_jobs, num_machines, jobs = parse_instance(instance_path)
    variables = parse_glpk_output(sol_path)

    if not variables:
        print(f"ERROR: no variable values found in {sol_path}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job", "operation", "machine", "start", "end"])

        for j in range(num_jobs):
            for k in range(num_machines):
                # GMPL model uses 1-indexed jobs and operations
                var_name = f"s[{j + 1},{k + 1}]"
                if var_name not in variables:
                    print(f"WARNING: {var_name} not in solution", file=sys.stderr)
                    continue

                start = int(round(variables[var_name]))
                machine_idx = jobs[j][k][0]   # 0-indexed from OR-Library
                duration_val = jobs[j][k][1]
                end = start + duration_val

                writer.writerow([j, k, machine_idx, start, end])

    print(f"Wrote schedule to {output_path}")


if __name__ == "__main__":
    main()
