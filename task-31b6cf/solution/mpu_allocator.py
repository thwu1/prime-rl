#!/usr/bin/env python3
"""
MPU Region Allocator for ARMv7-M PMSAv7.
Computes isolation-preserving MPU configurations for a Tock-like embedded OS.
"""

import json
import sys


def find_single_region(start, size):
    """Find the smallest valid PMSAv7 MPU region covering [start, start+size).

    Returns (base_address, region_size, subregion_disable).
    Region size is power-of-2, base is naturally aligned, SRD disables
    subregions entirely outside the target range.
    """
    end = start + size
    for log_s in range(5, 32):
        rs = 1 << log_s
        base = start & ~(rs - 1)
        if base + rs >= end:
            srs = rs // 8
            srd = 0
            for i in range(8):
                ss = base + i * srs
                se = ss + srs
                if se <= start or ss >= end:
                    srd |= (1 << i)
            return (base, rs, srd)
    raise ValueError(f"Cannot find region for [{hex(start)}, {hex(end)})")


def get_enabled_ranges(base, rs, srd):
    """Return list of (start, end) for enabled subregions."""
    srs = rs // 8
    return [
        (base + i * srs, base + (i + 1) * srs)
        for i in range(8)
        if not (srd & (1 << i))
    ]


def any_overlap(enabled_ranges, forbidden_ranges):
    """Check if any enabled range overlaps with any forbidden range."""
    for es, ee in enabled_ranges:
        for fs, fe in forbidden_ranges:
            if es < fe and fs < ee:
                return True
    return False


def compute_granted(regions):
    """Compute total granted bytes from a list of (base, size, srd) regions."""
    total = 0
    for base, rs, srd in regions:
        srs = rs // 8
        for i in range(8):
            if not (srd & (1 << i)):
                total += srs
    return total


def allocate_for_range(start, size, forbidden):
    """Allocate MPU region(s) for [start, start+size) that don't overlap forbidden ranges.

    Returns list of (base, region_size, srd) tuples.
    First tries a single region; if it violates isolation, splits at power-of-2
    boundaries and tries two regions.
    """
    end = start + size

    # Phase 1: try single region
    single = find_single_region(start, size)
    enabled = get_enabled_ranges(*single)
    if not any_overlap(enabled, forbidden):
        return [single]

    # Phase 2: split at power-of-2 boundaries
    best_result = None
    best_granted = float('inf')

    seen_boundaries = set()
    for log_b in range(5, 28):
        step = 1 << log_b
        b = ((start + step - 1) // step) * step
        if b <= start:
            b += step
        while b < end:
            if b not in seen_boundaries:
                seen_boundaries.add(b)

                r1 = find_single_region(start, b - start)
                r2 = find_single_region(b, end - b)

                e1 = get_enabled_ranges(*r1)
                e2 = get_enabled_ranges(*r2)

                if not any_overlap(e1, forbidden) and not any_overlap(e2, forbidden):
                    granted = compute_granted([r1, r2])
                    if granted < best_granted:
                        best_granted = granted
                        best_result = [r1, r2]
            b += step

    if best_result is not None:
        return best_result

    # Phase 3: recursive split (for pathological cases)
    for log_b in range(5, 28):
        step = 1 << log_b
        b = ((start + step - 1) // step) * step
        if b <= start:
            b += step
        if start < b < end:
            try:
                left = allocate_for_range(start, b - start, forbidden)
                right = allocate_for_range(b, end - b, forbidden)
                return left + right
            except ValueError:
                continue

    raise ValueError(
        f"Cannot allocate isolation-safe regions for [{hex(start)}, {hex(end)})"
    )


def main():
    with open("/app/memory_map.json") as f:
        mm = json.load(f)

    kernel_ranges = [
        (mm["kernel"]["flash"]["start"],
         mm["kernel"]["flash"]["start"] + mm["kernel"]["flash"]["size"]),
        (mm["kernel"]["ram"]["start"],
         mm["kernel"]["ram"]["start"] + mm["kernel"]["ram"]["size"]),
    ]

    processes = mm["processes"]
    config = {}

    for proc in processes:
        name = proc["name"]
        flash_start = proc["flash"]["start"]
        flash_size = proc["flash"]["size"]
        ram_start = proc["ram"]["start"]
        ram_size = proc["ram"]["size"]

        # Build forbidden ranges: kernel + all other processes' memory
        forbidden = list(kernel_ranges)
        for other in processes:
            if other["name"] != name:
                forbidden.append((
                    other["flash"]["start"],
                    other["flash"]["start"] + other["flash"]["size"]
                ))
                forbidden.append((
                    other["ram"]["start"],
                    other["ram"]["start"] + other["ram"]["size"]
                ))

        flash_regions = allocate_for_range(flash_start, flash_size, forbidden)
        ram_regions = allocate_for_range(ram_start, ram_size, forbidden)

        all_regions = flash_regions + ram_regions
        config[name] = {
            "regions": [
                {
                    "base_address": base,
                    "region_size": rs,
                    "subregion_disable": srd
                }
                for base, rs, srd in all_regions
            ]
        }

        print(f"{name}: {len(all_regions)} regions "
              f"(flash={len(flash_regions)}, ram={len(ram_regions)}), "
              f"granted={compute_granted(all_regions)} bytes, "
              f"allocated={flash_size + ram_size} bytes")

    with open("/app/mpu_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print("\nMPU configuration written to /app/mpu_config.json")


if __name__ == "__main__":
    main()
