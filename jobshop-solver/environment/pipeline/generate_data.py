#!/usr/bin/env python3
"""Convert an OR-Library JSP instance file to GMPL (.dat) format for glpsol."""

import sys


def parse_instance(filepath):
    """Parse OR-Library JSP format: first line is J M, then J lines of
    (machine, duration) pairs."""
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


def generate_gmpl_data(num_jobs, num_machines, jobs, output_path):
    """Write a GMPL data section compatible with jsp.mod."""
    all_durations = [d for job in jobs for _, d in job]
    big_m = max(all_durations)

    with open(output_path, "w") as f:
        f.write("data;\n\n")
        f.write(f"param J := {num_jobs};\n")
        f.write(f"param M := {num_machines};\n")
        f.write(f"param bigM := {big_m};\n\n")

        # Machine assignments — convert from 0-indexed (OR-Library) to
        # 1-indexed (GMPL model)
        col_hdr = "  ".join(str(k + 1) for k in range(num_machines))
        f.write(f"param machine :  {col_hdr} :=\n")
        for j in range(num_jobs):
            vals = "  ".join(str(jobs[j][k][0] + 1) for k in range(num_machines))
            f.write(f"  {j + 1}   {vals}\n")
        f.write(";\n\n")

        # Processing times (unchanged — durations are the same in both indexing
        # schemes)
        f.write(f"param duration :  {col_hdr} :=\n")
        for j in range(num_jobs):
            vals = "  ".join(str(jobs[j][k][1]) for k in range(num_machines))
            f.write(f"  {j + 1}   {vals}\n")
        f.write(";\n\n")

        f.write("end;\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <instance.txt> <output.dat>")
        sys.exit(1)

    num_jobs, num_machines, jobs = parse_instance(sys.argv[1])
    generate_gmpl_data(num_jobs, num_machines, jobs, sys.argv[2])
    print(f"Generated {sys.argv[2]}: {num_jobs} jobs x {num_machines} machines")
