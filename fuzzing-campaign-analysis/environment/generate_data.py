#!/usr/bin/env python3
"""Generate synthetic Magma campaign monitor data for benchmark task.

Creates a realistic workdir hierarchy matching the Magma captain output format,
with monitor CSV files containing per-bug reach/trigger counters.
"""

import os
import json

POLL = 5
DURATION = 300
NUM_POLLS = DURATION // POLL  # 60 data rows

# Campaign data specifications
# {fuzzer: {target: {program: {bugs: [...], reps: [{bug: (reach_sec, trigger_sec|None)}, ...]}}}}
# All times must be multiples of POLL. None = never reached/triggered.
CAMPAIGNS = {
    "afl": {
        "libpng": {
            "libpng_read_fuzzer": {
                "bugs": ["PNG001", "PNG002", "PNG003", "PNG004", "PNG005"],
                "reps": [
                    {"PNG001": (25, 60), "PNG002": (40, None), "PNG003": (75, 120),
                     "PNG004": (None, None), "PNG005": (15, 35)},
                    {"PNG001": (30, 70), "PNG002": (45, None), "PNG003": (90, 150),
                     "PNG004": (None, None), "PNG005": (20, 40)},
                    {"PNG001": (20, 55), "PNG002": (35, 150), "PNG003": (60, 100),
                     "PNG004": (None, None), "PNG005": (10, 30)},
                ]
            }
        },
        "libtiff": {
            "tiffcp": {
                "bugs": ["TIF001", "TIF002", "TIF003", "TIF004", "TIF005"],
                "reps": [
                    {"TIF001": (10, 25), "TIF002": (50, 80), "TIF003": (None, None),
                     "TIF004": (30, None), "TIF005": (70, 130)},
                    {"TIF001": (15, 30), "TIF002": (55, 90), "TIF003": (None, None),
                     "TIF004": (35, None), "TIF005": (75, 140)},
                    {"TIF001": (10, 20), "TIF002": (45, 75), "TIF003": (None, None),
                     "TIF004": (25, None), "TIF005": (65, 125)},
                ]
            }
        }
    },
    "aflplusplus": {
        "libpng": {
            "libpng_read_fuzzer": {
                "bugs": ["PNG001", "PNG002", "PNG003", "PNG004", "PNG005"],
                "reps": [
                    {"PNG001": (15, 35), "PNG002": (25, 80), "PNG003": (45, 70),
                     "PNG004": (200, None), "PNG005": (10, 20)},
                    {"PNG001": (20, 65), "PNG002": (30, 90), "PNG003": (50, 75),
                     "PNG004": (220, None), "PNG005": (15, 25)},
                    {"PNG001": (10, 30), "PNG002": (20, 70), "PNG003": (40, 65),
                     "PNG004": (180, None), "PNG005": (5, 15)},
                ]
            }
        },
        "libtiff": {
            "tiffcp": {
                "bugs": ["TIF001", "TIF002", "TIF003", "TIF004", "TIF005"],
                "reps": [
                    {"TIF001": (5, 10), "TIF002": (30, 50), "TIF003": (100, 200),
                     "TIF004": (20, 60), "TIF005": (40, 80)},
                    {"TIF001": (10, 15), "TIF002": (35, 55), "TIF003": (110, 210),
                     "TIF004": (25, 65), "TIF005": (45, 85)},
                    {"TIF001": (5, 10), "TIF002": (25, 45), "TIF003": (95, 190),
                     "TIF004": (15, 55), "TIF005": (35, 75)},
                ]
            }
        }
    },
    "honggfuzz": {
        "libpng": {
            "libpng_read_fuzzer": {
                "bugs": ["PNG001", "PNG002", "PNG003", "PNG004", "PNG005"],
                "reps": [
                    {"PNG001": (35, 80), "PNG002": (55, 120), "PNG003": (100, 180),
                     "PNG004": (None, None), "PNG005": (25, 50)},
                    {"PNG001": (40, 90), "PNG002": (60, 130), "PNG003": (110, 190),
                     "PNG004": (None, None), "PNG005": (30, 55)},
                    {"PNG001": (30, 75), "PNG002": (50, 110), "PNG003": (95, 170),
                     "PNG004": (None, None), "PNG005": (20, 45)},
                ]
            }
        },
        "libtiff": {
            "tiffcp": {
                "bugs": ["TIF001", "TIF002", "TIF003", "TIF004", "TIF005"],
                "reps": [
                    {"TIF001": (15, 20), "TIF002": (60, 100), "TIF003": (None, None),
                     "TIF004": (40, 90), "TIF005": (80, 160)},
                    {"TIF001": (20, 40), "TIF002": (65, 110), "TIF003": (None, None),
                     "TIF004": (45, 95), "TIF005": (85, 170)},
                    {"TIF001": (10, 15), "TIF002": (55, 95), "TIF003": (150, None),
                     "TIF004": (35, 85), "TIF005": (75, 155)},
                ]
            }
        }
    }
}


def generate_csv(bugs, rep_data, num_polls, poll):
    """Generate monitor CSV content for a single campaign.

    Format: header row with BUG_R,BUG_T columns, then one data row per poll
    interval with cumulative counter values.
    """
    lines = []

    # Column headers
    headers = []
    for bug in bugs:
        headers.append(bug + "_R")
        headers.append(bug + "_T")
    lines.append(",".join(headers))

    # Data rows: row N corresponds to time (N+1)*POLL
    for row_idx in range(num_polls):
        time_sec = (row_idx + 1) * poll
        values = []
        for bug in bugs:
            reach_time, trigger_time = rep_data.get(bug, (None, None))

            # Reach counter: cumulative, starts at 0, becomes >0 at reach_time
            if reach_time is not None and time_sec >= reach_time:
                reach_count = (time_sec - reach_time) // poll + 1
            else:
                reach_count = 0

            # Trigger counter: same pattern
            if trigger_time is not None and time_sec >= trigger_time:
                trigger_count = (time_sec - trigger_time) // poll + 1
            else:
                trigger_count = 0

            values.append(str(reach_count))
            values.append(str(trigger_count))

        lines.append(",".join(values))

    return "\n".join(lines) + "\n"


def main():
    workdir = "/app/workdir"

    # Generate normal campaign data
    for fuzzer, targets in CAMPAIGNS.items():
        for target, programs in targets.items():
            for program, spec in programs.items():
                bugs = spec["bugs"]
                reps = spec["reps"]

                for rep_idx, rep_data in enumerate(reps):
                    campaign_dir = os.path.join(
                        workdir, "ar", fuzzer, target, program, str(rep_idx)
                    )
                    os.makedirs(campaign_dir, exist_ok=True)

                    csv_content = generate_csv(bugs, rep_data, NUM_POLLS, POLL)

                    with open(os.path.join(campaign_dir, "monitor.csv"), "w") as f:
                        f.write(csv_content)

    # Edge case 1: Empty CSV file (completely empty, no header)
    empty_dir = os.path.join(
        workdir, "ar", "afl", "libpng", "libpng_read_fuzzer", "3"
    )
    os.makedirs(empty_dir, exist_ok=True)
    with open(os.path.join(empty_dir, "monitor.csv"), "w") as f:
        f.write("")

    # Edge case 2: Truncated CSV with no findings (short campaign, all zeros)
    trunc_dir = os.path.join(
        workdir, "ar", "honggfuzz", "libpng", "libpng_read_fuzzer", "3"
    )
    os.makedirs(trunc_dir, exist_ok=True)
    trunc_bugs = ["PNG001", "PNG002", "PNG003", "PNG004", "PNG005"]
    trunc_data = {b: (None, None) for b in trunc_bugs}
    csv_content = generate_csv(trunc_bugs, trunc_data, 20, POLL)
    with open(os.path.join(trunc_dir, "monitor.csv"), "w") as f:
        f.write(csv_content)

    # Write captainrc configuration
    with open(os.path.join(workdir, "captainrc"), "w") as f:
        f.write("POLL=5\n")
        f.write("TIMEOUT=5m\n")
        f.write("REPEAT=3\n")
        f.write("FUZZERS=(afl aflplusplus honggfuzz)\n")

    print("Data generation complete.")
    print("Normal campaigns: %d" % (3 * 2 * 3))
    print("Edge case campaigns: 2 (empty CSV, truncated CSV)")


if __name__ == "__main__":
    main()
