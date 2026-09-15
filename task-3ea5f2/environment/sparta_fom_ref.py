#!/usr/bin/env python3
"""ATS-5 SPARTA FOM extraction script.

Extracts the Figure of Merit from SPARTA simulation log files per the
ATS-5 benchmark specification. The FOM is the harmonic mean of per-timestep
Mega-particle-steps/sec computed from the Loop statistics block between 300
and 600 seconds of wall time, normalized by compute node count.

Based on the Crossroads/ATS-5 benchmark suite (v2.71).
"""

import sys
import os

NUM_RANKS_PER_NODE = 112


def parse_and_compute(filepath, ranks_per_node=NUM_RANKS_PER_NODE):
    """Parse a SPARTA log file and compute the ATS-5 FOM.

    Parameters
    ----------
    filepath : str
        Path to SPARTA log file.
    ranks_per_node : int
        Number of MPI ranks per compute node (default: 112 for Crossroads).

    Returns
    -------
    dict or None
        FOM result dictionary, or None if computation fails.
    """
    num_ranks = None
    ppc = None
    length_scale = None
    loop_block = []
    in_block = False
    wall_time = None
    total_steps = None
    total_particles = None

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()

            # Extract MPI rank count from header
            if num_ranks is None:
                if "Running on" in stripped and "MPI task(s)" in stripped:
                    num_ranks = int(stripped.split()[2])

            # Extract simulation parameters
            if ppc is None:
                if ("variable" in stripped and "ppc" in stripped
                        and "equal" in stripped):
                    parts = stripped.split()
                    if len(parts) == 4:
                        try:
                            ppc = int(parts[3])
                        except ValueError:
                            pass

            if length_scale is None:
                if ("variable" in stripped and " L " in stripped
                        and "equal" in stripped):
                    parts = stripped.split()
                    if len(parts) == 4:
                        try:
                            length_scale = float(parts[3])
                        except ValueError:
                            pass

            # Detect start of Loop statistics block
            if ("Step" in stripped and "CPU" in stripped
                    and "Np" in stripped and "Natt" in stripped
                    and "Ncoll" in stripped and "Maxlevel" in stripped):
                in_block = True
                continue

            # Detect end of Loop statistics block
            if "Loop time of" in stripped and "steps with" in stripped:
                parts = stripped.split()
                wall_time = float(parts[3])
                total_steps = int(parts[8])
                total_particles = int(parts[11])
                in_block = False
                break

            # Parse statistics rows
            if in_block:
                parts = stripped.split()
                if len(parts) == 6:
                    try:
                        loop_block.append([
                            int(parts[0]),      # Step
                            float(parts[1]),    # CPU (elapsed seconds)
                            int(parts[2]),      # Np (particles)
                            int(parts[3]),      # Natt (collision attempts)
                            int(parts[4]),      # Ncoll (collisions)
                            int(parts[5]),      # Maxlevel
                        ])
                    except (ValueError, IndexError):
                        pass

    # Validate extracted data
    if num_ranks is None:
        return None
    if wall_time is None or wall_time < 600.0:
        return None

    num_nodes = round(num_ranks / ranks_per_node)
    if num_nodes < 1:
        return None

    # Compute FOM: harmonic mean of Mega-particle-steps/sec
    # in the 300-600 second steady-state window
    reciprocals = []
    for row in loop_block:
        cpu_time = row[1]
        if cpu_time >= 600.0:
            break
        if cpu_time >= 300.0:
            step = row[0]
            np_val = row[2]
            if step > 0 and cpu_time > 0:
                qoi = step * np_val / cpu_time / 1e6
                reciprocals.append(1.0 / qoi)

    if not reciprocals:
        return None

    hmean_fom = len(reciprocals) / sum(reciprocals)
    fom_per_node = hmean_fom / num_nodes

    return {
        "fom_per_node": fom_per_node,
        "num_ranks": num_ranks,
        "num_nodes": num_nodes,
        "wall_time": wall_time,
        "total_steps": total_steps,
        "total_particles": total_particles,
        "ppc": ppc,
        "length_scale": length_scale,
    }


def main():
    """Command-line interface for SPARTA FOM extraction."""
    if len(sys.argv) < 2:
        print("Usage: {} <log_file> [ranks_per_node]".format(sys.argv[0]))
        print()
        print("Extract the ATS-5 Figure of Merit from a SPARTA log file.")
        print()
        print("Arguments:")
        print("  log_file        Path to SPARTA log file")
        print("  ranks_per_node  MPI ranks per node (default: {})".format(
            NUM_RANKS_PER_NODE))
        sys.exit(1)

    log_file = sys.argv[1]
    rpn = int(sys.argv[2]) if len(sys.argv) > 2 else NUM_RANKS_PER_NODE

    if not os.path.exists(log_file):
        print("ERROR: File not found: {}".format(log_file))
        sys.exit(1)

    result = parse_and_compute(log_file, rpn)

    if result is None:
        print("ERROR: Could not compute FOM for {}".format(log_file))
        print("Possible causes:")
        print("  - Wall time < 600 seconds (minimum required)")
        print("  - Missing or malformed statistics block")
        print("  - No data rows in the 300-600 second window")
        sys.exit(2)

    print("=" * 60)
    print("SPARTA ATS-5 FOM Report")
    print("=" * 60)
    print("File:             {}".format(os.path.abspath(log_file)))
    print("MPI Ranks:        {}".format(result["num_ranks"]))
    print("Compute Nodes:    {}".format(result["num_nodes"]))
    print("Wall Time:        {:.3f} sec".format(result["wall_time"]))
    print("Total Steps:      {}".format(result["total_steps"]))
    print("Final Particles:  {}".format(result["total_particles"]))
    if result["ppc"] is not None:
        print("PPC:              {}".format(result["ppc"]))
    if result["length_scale"] is not None:
        print("L Scale:          {}".format(result["length_scale"]))
    print("-" * 60)
    print("FOM:              {:.4f} M-particle-steps/sec/node".format(
        result["fom_per_node"]))
    print("=" * 60)


if __name__ == "__main__":
    main()
