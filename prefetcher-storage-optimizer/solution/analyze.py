#!/usr/bin/env python3

"""
PIPS prefetcher hardware storage budget audit and design-space analysis.
Reads gcc -dM -E output for resolved macro values, derives the storage
formula from the prefetcher's C++ source structure, and explores the
configuration space for optimal tradeoffs.
"""

import re
import json
import math
import sys


def parse_gcc_macros(macro_file="/tmp/pips_macros.txt"):
    """
    Parse gcc -dM -E output to extract resolved macro definitions.
    Returns a dict of macro_name -> integer_value for object-like macros.
    """
    raw = {}
    with open(macro_file) as f:
        for line in f:
            line = line.strip()
            m = re.match(r"#define\s+(\w+)\s+(.+)", line)
            if m:
                name = m.group(1)
                expr = m.group(2).strip()
                raw[name] = expr

    # Resolve macro values with multiple passes for dependencies
    resolved = {}
    for _ in range(10):
        progress = False
        for name, expr in raw.items():
            if name in resolved:
                continue
            # Substitute already-resolved names into expression
            subst_expr = expr
            for rname, rval in resolved.items():
                subst_expr = re.sub(
                    r"\b" + re.escape(rname) + r"\b", str(rval), subst_expr
                )
            # Strip C type suffixes (UL, ULL, L, U, LL)
            subst_expr = re.sub(r"\b(\d+)[UuLl]+\b", r"\1", subst_expr)
            try:
                val = eval(subst_expr, {"__builtins__": {}}, {})
                if isinstance(val, (int, float)):
                    resolved[name] = int(val)
                    progress = True
            except Exception:
                pass
        if not progress:
            break

    return resolved


def compute_storage(ntargets, offsetbits, cbits, tagbits,
                    lht_logsets, lht_numways, lht_rpbits,
                    scc_logsets, scc_numways, scc_rpbits,
                    nscouts, log2_block_size):
    """
    Compute total hardware storage in bits for a PIPS configuration.

    Storage formula derived from the C++ source:
      LHT_ENTRY::size() = NTARGETS * OFFSETBITS + (NTARGETS+1) * CBITS
      LINE_HISTORY_TABLE::size() = n * (LHT_ENTRY::size() + TAGBITS + rpbits)
        where n = numways << logsets
      Misc state: frontline, prevline (cache-line addresses),
                  scout[NSCOUTS] (cache-line addresses), ns (round-robin index)
    """
    # Per-entry data bits (from LHT_ENTRY::size() static method)
    entry_data_bits = ntargets * offsetbits + (ntargets + 1) * cbits

    # Per-entry total bits including tag and replacement policy
    lht_entry_bits = entry_data_bits + tagbits + lht_rpbits
    scc_entry_bits = entry_data_bits + tagbits + scc_rpbits

    # Number of entries (from constructor: n = nway << lset)
    lht_entries = lht_numways << lht_logsets
    scc_entries = scc_numways << scc_logsets

    # Table storage (from size(): nbits * n)
    lht_bits = lht_entries * lht_entry_bits
    scc_bits = scc_entries * scc_entry_bits

    # Miscellaneous register state
    # Cache-line address width = 64 - LOG2_BLOCK_SIZE
    cache_line_addr_bits = 64 - log2_block_size
    # frontline + prevline = 2 cache-line addresses
    # scout[NSCOUTS] = NSCOUTS cache-line addresses
    # ns = round-robin index over NSCOUTS scouts
    ns_bits = max(1, math.ceil(math.log2(nscouts))) if nscouts > 1 else 1
    misc_bits = (2 + nscouts) * cache_line_addr_bits + ns_bits

    total_bits = lht_bits + scc_bits + misc_bits
    total_kb = total_bits / 8192.0  # 1 KB = 8192 bits

    return {
        "entry_data_bits": entry_data_bits,
        "lht_entry_bits": lht_entry_bits,
        "scc_entry_bits": scc_entry_bits,
        "lht_entries": lht_entries,
        "scc_entries": scc_entries,
        "lht_bits": lht_bits,
        "scc_bits": scc_bits,
        "misc_bits": misc_bits,
        "total_bits": total_bits,
        "total_kb": total_kb,
        "within_budget": total_bits <= 1048576,
    }


def main():
    # ── Parse gcc preprocessor output for resolved macro values ──
    macros = parse_gcc_macros()

    # Extract PIPS configuration parameters
    ntargets = macros.get("NTARGETS", 3)
    offsetbits = macros.get("OFFSETBITS", 22)
    cbits = macros.get("CBITS", 4)
    tagbits = macros.get("TAGBITS", 16)
    lht_logsets = macros.get("LHT_LOGSETS", 10)
    lht_numways = macros.get("LHT_NUMWAYS", 10)
    lht_rpbits = macros.get("LHT_RPBITS", 3)
    scc_logsets = macros.get("SCC_LOGSETS", 5)
    scc_numways = macros.get("SCC_NUMWAYS", 4)
    scc_rpbits = macros.get("SCC_RPBITS", 2)
    nscouts = macros.get("NSCOUTS", 4)
    log2_block_size = macros.get("LOG2_BLOCK_SIZE", 6)

    # ── Compute original configuration storage ──────────────────
    original_storage = compute_storage(
        ntargets, offsetbits, cbits, tagbits,
        lht_logsets, lht_numways, lht_rpbits,
        scc_logsets, scc_numways, scc_rpbits,
        nscouts, log2_block_size
    )

    print(f"Original config storage: {original_storage['total_bits']} bits "
          f"({original_storage['total_kb']:.4f} KB)")
    print(f"  LHT: {original_storage['lht_bits']} bits "
          f"({original_storage['lht_entries']} entries x "
          f"{original_storage['lht_entry_bits']} bits)")
    print(f"  SCC: {original_storage['scc_bits']} bits "
          f"({original_storage['scc_entries']} entries x "
          f"{original_storage['scc_entry_bits']} bits)")
    print(f"  Misc: {original_storage['misc_bits']} bits")
    print(f"  Within 128KB budget: {original_storage['within_budget']}")

    # ── Design space sweep ──────────────────────────────────────
    budget_bits = 1048576  # 128 KB
    total_evaluated = 0
    valid_configs = []

    for ob in range(12, 29):       # OFFSETBITS: 12..28
        for ls in range(6, 15):    # LHT_LOGSETS: 6..14
            for nw in range(1, 17):  # LHT_NUMWAYS: 1..16
                total_evaluated += 1
                storage = compute_storage(
                    ntargets, ob, cbits, tagbits,
                    ls, nw, lht_rpbits,
                    scc_logsets, scc_numways, scc_rpbits,
                    nscouts, log2_block_size
                )
                if storage["within_budget"]:
                    lht_entries = storage["lht_entries"]
                    max_reach = 1 << (ob - 1)
                    valid_configs.append({
                        "offsetbits": ob,
                        "logsets": ls,
                        "numways": nw,
                        "lht_entries": lht_entries,
                        "max_reach": max_reach,
                        "total_bits": storage["total_bits"],
                    })

    print(f"\nSweep: {len(valid_configs)} valid / {total_evaluated} evaluated")

    # ── Build non-dominated frontier ────────────────────────────
    # For each OFFSETBITS, find the config with maximum lht_entries
    best_per_ob = {}
    for c in valid_configs:
        ob = c["offsetbits"]
        if ob not in best_per_ob or c["lht_entries"] > best_per_ob[ob]["lht_entries"]:
            best_per_ob[ob] = c
        elif c["lht_entries"] == best_per_ob[ob]["lht_entries"]:
            if c["logsets"] > best_per_ob[ob]["logsets"]:
                best_per_ob[ob] = c

    # Sort by lht_entries descending, then max_reach descending
    sorted_candidates = sorted(
        best_per_ob.values(), key=lambda c: (-c["lht_entries"], -c["max_reach"])
    )

    # Sweep to build the non-dominated frontier
    pareto_front = []
    max_reach_seen = -1
    for c in sorted_candidates:
        if c["max_reach"] > max_reach_seen:
            pareto_front.append(c)
            max_reach_seen = c["max_reach"]

    # Compute combined score (harmonic mean) for each frontier point
    for p in pareto_front:
        e, r = p["lht_entries"], p["max_reach"]
        p["combined_score"] = 2.0 * e * r / (e + r)

    print(f"Non-dominated frontier: {len(pareto_front)} points")
    for p in pareto_front:
        print(
            f"  OB={p['offsetbits']:2d}  entries={p['lht_entries']:5d}  "
            f"reach={p['max_reach']:>12d}  score={p['combined_score']:.2f}"
        )

    # ── Best combined metric ────────────────────────────────────
    best_combined = max(pareto_front, key=lambda p: p["combined_score"])

    print(
        f"\nBest combined: OB={best_combined['offsetbits']}, "
        f"entries={best_combined['lht_entries']}, "
        f"reach={best_combined['max_reach']}, "
        f"score={best_combined['combined_score']:.2f}"
    )

    # ── Write output ────────────────────────────────────────────
    output = {
        "original_config": original_storage,
        "sweep": {
            "total_configs_evaluated": total_evaluated,
            "valid_configs": len(valid_configs),
        },
        "pareto_front": [
            {
                "offsetbits": p["offsetbits"],
                "logsets": p["logsets"],
                "numways": p["numways"],
                "lht_entries": p["lht_entries"],
                "max_reach": p["max_reach"],
                "total_bits": p["total_bits"],
                "combined_score": p["combined_score"],
            }
            for p in pareto_front
        ],
        "best_combined": {
            "offsetbits": best_combined["offsetbits"],
            "logsets": best_combined["logsets"],
            "numways": best_combined["numways"],
            "lht_entries": best_combined["lht_entries"],
            "max_reach": best_combined["max_reach"],
            "combined_score": best_combined["combined_score"],
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
