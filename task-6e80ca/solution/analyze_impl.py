#!/usr/bin/env python3
"""
SLUB Heap Exploit Planner — analyzes a Linux kernel heap vulnerability
and produces a SLUB-aware exploitation feasibility report.
"""

import argparse
import json
import sys

# Standard x86_64 kmalloc size classes (SLUB allocator)
KMALLOC_SIZES = [8, 16, 32, 64, 96, 128, 192, 256, 512, 1024, 2048, 4096, 8192]


def parse_slabinfo(path):
    """Parse /proc/slabinfo v2.1 format into a dict keyed by cache name."""
    caches = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("slabinfo"):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            name = parts[0]
            try:
                caches[name] = {
                    "name": name,
                    "active_objs": int(parts[1]),
                    "num_objs": int(parts[2]),
                    "objsize": int(parts[3]),
                    "objperslab": int(parts[4]),
                    "pagesperslab": int(parts[5]),
                }
            except (ValueError, IndexError):
                continue
    return caches


def kmalloc_cache_name(size, account=False):
    """Map an allocation size to the correct kmalloc cache name.

    With CONFIG_MEMCG_KMEM=y, GFP_KERNEL_ACCOUNT allocations go to
    kmalloc-cg-N caches, while GFP_KERNEL goes to kmalloc-N.
    """
    prefix = "kmalloc-cg-" if account else "kmalloc-"
    for s in KMALLOC_SIZES:
        if size <= s:
            return f"{prefix}{s}", s
    return None, None


def _prev_kmalloc_size(target_size):
    """Return the largest kmalloc size class strictly smaller than target_size."""
    idx = KMALLOC_SIZES.index(target_size)
    return KMALLOC_SIZES[idx - 1] if idx > 0 else 0


def object_fits_cache(struct, target_cache_name, target_cache_size):
    """Check whether a kernel object can be allocated in the target cache.

    Returns (fits: bool, alloc_size_to_use: int|None).
    """
    # Dedicated caches are never mergeable with kmalloc
    if struct.get("cache_type") == "dedicated":
        return False, None

    # Must be userspace-triggerable for practical exploitation
    if not struct.get("userspace_triggerable", False):
        return False, None

    # Determine whether this object's GFP flags match the target cache family
    flags = struct.get("alloc_flags", "GFP_KERNEL")
    is_account = "ACCOUNT" in flags

    prev_size = _prev_kmalloc_size(target_cache_size)

    if struct.get("variable_size", False):
        min_size, max_size = struct.get("total_size_range", [0, 0])
        # Object needs to produce a total allocation in (prev_size, target_cache_size]
        if min_size > target_cache_size:
            return False, None
        if max_size <= prev_size:
            return False, None
        # Verify the cache family matches
        cache_name, _ = kmalloc_cache_name(target_cache_size, is_account)
        if cache_name != target_cache_name:
            return False, None
        # Use target_cache_size as the allocation size for analysis
        return True, target_cache_size
    else:
        size = struct.get("base_size", 0)
        cache_name, _ = kmalloc_cache_name(size, is_account)
        if cache_name == target_cache_name:
            return True, size
        return False, None


def score_candidate(struct, alloc_size, deref_offset, deref_type):
    """Score a candidate spray object for exploitation potential.

    Returns (score, data_control_at_offset, attack_type).
    """
    score = 0.0
    data_control = False
    attack_type = "data_corruption"

    # --- Lifetime ---
    lifetime = struct.get("lifetime", "unknown")
    if lifetime == "persistent":
        score += 0.3
    elif lifetime == "ephemeral":
        score += 0.1

    # --- Arbitrary data control at the dereference offset ---
    user_data_offset = struct.get("user_data_offset")
    arbitrary = struct.get("arbitrary_user_data", False)

    if user_data_offset is not None and arbitrary:
        if user_data_offset <= deref_offset and deref_offset + 8 <= alloc_size:
            data_control = True
            score += 0.5
            if deref_type == "function_ptr":
                attack_type = "control_flow_hijack"
            else:
                attack_type = "data_corruption"

    # --- Function pointers in the object (useful for info-leak pivot) ---
    fields = struct.get("fields", [])
    has_fptrs = any("function_ptr" in f.get("type", "") for f in fields)
    if has_fptrs:
        score += 0.05

    # --- Function pointer at exactly the dereference offset (info-leak value) ---
    for field in fields:
        if field.get("offset") == deref_offset and "function_ptr" in field.get("type", ""):
            score += 0.1
            if not data_control:
                attack_type = "info_leak"

    return round(score, 2), data_control, attack_type


def analyze(slabinfo_path, structs_path, scenario_path):
    """Run the full analysis and return the result dict."""
    caches = parse_slabinfo(slabinfo_path)
    with open(structs_path) as f:
        structs = json.load(f)
    with open(scenario_path) as f:
        scenario = json.load(f)

    # --- Identify target cache ---
    obj_size = scenario["object_size"]
    alloc_flags = scenario.get("alloc_flags", "GFP_KERNEL")
    is_account = "ACCOUNT" in alloc_flags
    target_cache_name, target_cache_size = kmalloc_cache_name(obj_size, is_account)

    cache_info = caches.get(target_cache_name, {})
    objs_per_slab = cache_info.get("objperslab", 0)
    pages_per_slab = cache_info.get("pagesperslab", 0)

    # --- Dereference info ---
    deref_offsets = scenario.get("dereference_offsets", [])
    primary_deref = deref_offsets[0] if deref_offsets else {}
    deref_offset = primary_deref.get("offset", 0)
    deref_type = primary_deref.get("type", "unknown")

    # --- Find and score compatible objects ---
    candidates = []
    for struct in structs:
        fits, alloc_size = object_fits_cache(struct, target_cache_name, target_cache_size)
        if not fits:
            continue

        sc, data_control, attack_type = score_candidate(
            struct, alloc_size, deref_offset, deref_type
        )

        candidates.append({
            "name": struct["name"],
            "score": sc,
            "data_control_at_deref_offset": data_control,
            "lifetime": struct.get("lifetime", "unknown"),
            "trigger": struct.get("trigger_method", "unknown"),
            "attack_type": attack_type,
        })

    # Sort by score descending, then name ascending for stability
    candidates.sort(key=lambda c: (-c["score"], c["name"]))

    # --- Spray parameters ---
    slab_fill_count = 10
    recommended_spray = objs_per_slab * slab_fill_count if objs_per_slab else 160

    # --- Recommended strategy ---
    # Prefer persistent objects with data control
    best = None
    for c in candidates:
        if c["data_control_at_deref_offset"]:
            if best is None or c["lifetime"] == "persistent":
                best = c
                if c["lifetime"] == "persistent":
                    break

    if best is None and candidates:
        best = candidates[0]

    strategy = None
    if best:
        strategy = {
            "spray_object": best["name"],
            "attack_type": best["attack_type"],
        }

    return {
        "target_cache": {
            "name": target_cache_name,
            "objsize": target_cache_size,
            "objs_per_slab": objs_per_slab,
            "pages_per_slab": pages_per_slab,
        },
        "candidates": candidates,
        "spray_params": {
            "objs_per_slab": objs_per_slab,
            "recommended_spray_count": recommended_spray,
        },
        "strategy": strategy,
    }


def main():
    parser = argparse.ArgumentParser(description="SLUB Heap Exploit Planner")
    parser.add_argument("--slabinfo", required=True, help="Path to slabinfo dump")
    parser.add_argument("--structs", required=True, help="Path to kernel structs JSON")
    parser.add_argument("--scenario", required=True, help="Path to vulnerability scenario JSON")
    args = parser.parse_args()

    result = analyze(args.slabinfo, args.structs, args.scenario)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
