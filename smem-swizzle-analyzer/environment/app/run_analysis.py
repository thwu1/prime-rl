#!/usr/bin/env python3
"""Run shared memory bank conflict analysis on all configurations.

Reads configurations from /app/configs.json, analyzes each one for
bank conflicts with and without XOR swizzling, and writes results
to /app/results.json.
"""

import json
import sys
from functools import partial

from smem_analyzer.banking import count_bank_conflicts
from smem_analyzer.swizzle import apply_swizzle, verify_bijective
from smem_analyzer.patterns import (
    DTYPE_SIZES,
    generate_column_addresses,
    generate_column_addresses_swizzled,
    generate_row_addresses,
    generate_row_addresses_swizzled,
)


def analyze_config(config):
    """Analyze a single shared memory configuration.

    Args:
        config: Dict with keys: name, NX, NY, dtype, access

    Returns:
        Dict with analysis results
    """
    name = config["name"]
    NX = config["NX"]
    NY = config["NY"]
    sizeof_T = DTYPE_SIZES[config["dtype"]]
    access = config["access"]

    # Create a swizzle function with NX, sizeof_T, sizeof_TC pre-bound
    swizzle_fn = partial(apply_swizzle, NX=NX, sizeof_T=sizeof_T, sizeof_TC=4)

    # Generate access patterns and count bank conflicts
    if access == "column":
        addrs_plain = generate_column_addresses(NX, NY, 0, sizeof_T)
        addrs_swizzled = generate_column_addresses_swizzled(
            NX, NY, 0, sizeof_T, swizzle_fn
        )
    elif access == "row":
        addrs_plain = generate_row_addresses(NX, NY, 0, sizeof_T)
        addrs_swizzled = generate_row_addresses_swizzled(
            NX, NY, 0, sizeof_T, swizzle_fn
        )
    else:
        raise ValueError(f"Unknown access pattern: {access}")

    conflicts_no_swizzle = count_bank_conflicts(addrs_plain)
    conflicts_swizzle = count_bank_conflicts(addrs_swizzled)
    bijective = verify_bijective(NX, NY, sizeof_T, 4)

    return {
        "name": name,
        "conflicts_no_swizzle": conflicts_no_swizzle,
        "conflicts_swizzle": conflicts_swizzle,
        "bijective": bijective,
    }


def main():
    config_path = "/app/configs.json"
    output_path = "/app/results.json"

    with open(config_path) as f:
        configs = json.load(f)

    results = []
    for config in configs:
        print(f"Analyzing {config['name']}...", end=" ")
        try:
            result = analyze_config(config)
            results.append(result)
            print(
                f"no_swz={result['conflicts_no_swizzle']}, "
                f"swz={result['conflicts_swizzle']}, "
                f"bij={result['bijective']}"
            )
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
