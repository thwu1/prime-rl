#!/usr/bin/env python3
"""Generate synthetic SPARTA DSMC log files and manifest for the forensics task.

Produces deterministic log files resembling real SPARTA output from a DOE ATS-5
weak-scaling benchmark study. The data embeds several realistic data-quality
issues that the agent must discover and handle:

1. scaling_16.log has a restart (two statistics blocks); only the second
   (complete) block should be used for FOM computation.
2. validation.log has 2688 MPI ranks (24 nodes), but the manifest incorrectly
   claims 32 nodes (3584 ranks).
3. The reference FOM script uses >= 300 (should be > 300) and only reads
   the first statistics block (breaks on restart logs).

The base_dt values follow a power-law: base_dt(p) = 15.20 * p^0.035,
which produces FOM values that follow FOM(p) ~ a * p^(-0.035).
"""

import random
import os
import json

RANKS_PER_NODE = 112
MAX_STEP = 4400
STATS_INTERVAL = 100
LOG_DIR = "/app/data/logs"
MANIFEST_PATH = "/app/data/manifest.json"

CONFIGS = {
    "scaling_1": {
        "nodes": 1, "base_np": 10_052_400,
        "base_dt": 15.20, "dt_growth": 0.015, "seed": 42,
        "ppc": 35, "L": 1,
    },
    "scaling_4": {
        "nodes": 4, "base_np": 40_209_600,
        "base_dt": 15.96, "dt_growth": 0.015, "seed": 43,
        "ppc": 35, "L": 2,
    },
    "scaling_16": {
        "nodes": 16, "base_np": 160_838_400,
        "base_dt": 16.75, "dt_growth": 0.015, "seed": 44,
        "ppc": 35, "L": 4,
        "restart": True, "abort_step": 2000,
    },
    "scaling_64": {
        "nodes": 64, "base_np": 643_353_600,
        "base_dt": 17.58, "dt_growth": 0.015, "seed": 45,
        "ppc": 35, "L": 8,
    },
    "validation": {
        "nodes": 24, "base_np": 241_257_600,
        "base_dt": 17.00, "dt_growth": 0.015, "seed": 46,
        "ppc": 35, "L": 6,
    },
}


def generate_stats_block(cfg, max_step, seed):
    """Generate a single statistics block (header line, data rows, footer)."""
    num_ranks = cfg["nodes"] * RANKS_PER_NODE
    random.seed(seed)

    header_line = "    Step          CPU        Np     Natt    Ncoll Maxlevel"
    rows = []
    cpu = 0.0

    for step in range(0, max_step + 1, STATS_INTERVAL):
        if step == 0:
            np_val = cfg["base_np"]
            natt = 0
            ncoll = 0
        else:
            k = step // STATS_INTERVAL
            cpu += cfg["base_dt"] + cfg["dt_growth"] * k
            np_val = cfg["base_np"] + random.randint(-2000, 2000)
            natt = int(step * 1.0) + random.randint(-20, 20)
            ncoll = int(natt * 0.85) + random.randint(-15, 15)

        rows.append(
            "    {:>5}    {:>12.5f} {:>11} {:>8} {:>8}        6".format(
                step, cpu, np_val, natt, ncoll
            )
        )

    final_np = cfg["base_np"] + random.randint(-2000, 2000)
    footer = "Loop time of {:.3f} on {} procs for {} steps with {} particles".format(
        cpu, num_ranks, max_step, final_np
    )

    return header_line, rows, footer


def generate_log(name, cfg):
    """Generate a complete SPARTA log file."""
    num_ranks = cfg["nodes"] * RANKS_PER_NODE

    lines = [
        "SPARTA (13 Apr 2023)",
        "KOKKOS mode is enabled (../kokkos.cpp:40)",
        "  requested 0 GPU(s) per node",
        "  requested 1 thread(s) per MPI task",
        "Running on {} MPI task(s)".format(num_ranks),
        "package kokkos",
        "",
        "variable            ppc equal {}".format(cfg["ppc"]),
        "variable            L equal {}".format(cfg["L"]),
        "",
        "seed                56789",
        "dimension           3",
        "global              gridcut 0.01 comm/sort yes surfmax 300 splitmax 100",
        "",
        "collide_modify      vremax 100 yes vibrate no rotate smooth nearcp yes 10",
        "stats               {}".format(STATS_INTERVAL),
    ]

    if cfg.get("restart"):
        abort_step = cfg["abort_step"]

        # First (aborted) run
        lines.append("run                 {}".format(abort_step))
        lines.append("")
        header, rows, footer = generate_stats_block(cfg, abort_step, cfg["seed"])
        lines.append(header)
        lines.extend(rows)
        lines.append(footer)

        # Restart section
        lines.append("")
        lines.append("SPARTA (13 Apr 2023)")
        lines.append("  read_restart restart.{}.checkpoint".format(abort_step))
        lines.append("  restarting at step {}".format(abort_step))
        lines.append("")

        # Second (complete) run with different seed for variation
        lines.append("run                 {}".format(MAX_STEP))
        lines.append("")
        header2, rows2, footer2 = generate_stats_block(
            cfg, MAX_STEP, cfg["seed"] + 100
        )
        lines.append(header2)
        lines.extend(rows2)
        lines.append(footer2)
    else:
        lines.append("run                 {}".format(MAX_STEP))
        lines.append("")
        header, rows, footer = generate_stats_block(cfg, MAX_STEP, cfg["seed"])
        lines.append(header)
        lines.extend(rows)
        lines.append(footer)

    return "\n".join(lines) + "\n"


def generate_manifest():
    """Generate run manifest with intentional discrepancy for validation run."""
    return {
        "study_name": "ATS-5 SPARTA Weak Scaling Study",
        "system": "Crossroads (CTS-2)",
        "ranks_per_node": RANKS_PER_NODE,
        "runs": {
            "scaling_1": {
                "nodes": 1,
                "total_ranks": 1 * RANKS_PER_NODE,
                "log_file": "scaling_1.log",
            },
            "scaling_4": {
                "nodes": 4,
                "total_ranks": 4 * RANKS_PER_NODE,
                "log_file": "scaling_4.log",
            },
            "scaling_16": {
                "nodes": 16,
                "total_ranks": 16 * RANKS_PER_NODE,
                "log_file": "scaling_16.log",
            },
            "scaling_64": {
                "nodes": 64,
                "total_ranks": 64 * RANKS_PER_NODE,
                "log_file": "scaling_64.log",
            },
            "validation": {
                "nodes": 32,
                "total_ranks": 32 * RANKS_PER_NODE,
                "log_file": "validation.log",
            },
        },
    }


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)

    for name, cfg in CONFIGS.items():
        content = generate_log(name, cfg)
        path = os.path.join(LOG_DIR, "{}.log".format(name))
        with open(path, "w") as f:
            f.write(content)
        print("Generated {}".format(path))

    with open(MANIFEST_PATH, "w") as f:
        json.dump(generate_manifest(), f, indent=2)
    print("Generated {}".format(MANIFEST_PATH))


if __name__ == "__main__":
    main()
