#!/usr/bin/env python3
"""Generate a JSON report from structured and flat encoded outputs."""

import json
import sys
import numpy as np


def main():
    if len(sys.argv) != 5:
        print("Usage: gen_report.py <structured.npy> <flat.npy> <n_bins> <output.json>",
              file=sys.stderr)
        sys.exit(1)

    structured = np.load(sys.argv[1])
    flat = np.load(sys.argv[2])
    n_bins_requested = int(sys.argv[3])
    output_path = sys.argv[4]

    report = {
        "n_samples": int(structured.shape[0]),
        "n_features": int(structured.shape[1]),
        "n_bins_requested": n_bins_requested,
        "structured_shape": [int(d) for d in structured.shape],
        "flat_width": int(flat.shape[1]),
    }

    with open(output_path, "w") as f:
        json.dump(report, f)


if __name__ == "__main__":
    main()
