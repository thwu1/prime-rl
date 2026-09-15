#!/usr/bin/env python3
"""Generate sweep summary JSON from bin-count subdirectories."""

import json
import sys
import numpy as np


def main():
    if len(sys.argv) != 3:
        print("Usage: gen_sweep.py <outdir> <output.json>", file=sys.stderr)
        sys.exit(1)

    outdir = sys.argv[1]
    output_path = sys.argv[2]

    sweep = {}
    for n in [4, 8, 16, 32, 64]:
        s = np.load(f"{outdir}/bins_{n}/structured.npy")
        f = np.load(f"{outdir}/bins_{n}/flat.npy")
        sweep[str(n)] = {
            "structured_shape": [int(d) for d in s.shape],
            "flat_width": int(f.shape[1]),
        }

    with open(output_path, "w") as fh:
        json.dump(sweep, fh)


if __name__ == "__main__":
    main()
