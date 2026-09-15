#!/usr/bin/env python3

"""
PIPS Prefetcher Configuration Space Optimizer

Parses the PIPS (Probabilistic Instruction Prefetching with Scouting)
C++ source code to extract its parametric configuration, derives the
hardware storage budget formula, and performs a parameter sweep to find
Pareto-optimal configurations within the IPC-1 128 KB budget.
"""

import re
import json
import math
import sys


def parse_defines(source_code):
    """
    Extract #define constants from C++ source code and resolve them to
    integer values. Handles simple expressions like (1<<N)-1 and
    references to other defines.
    """
    raw_defines = {}
    for line in source_code.split("\n"):
        stripped = line.strip()
        # Skip commented-out defines
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        m = re.match(r"#define\s+(\w+)\s+(.+?)(?:\s*//.*)?$", stripped)
        if m:
            name = m.group(1)
            expr = m.group(2).strip()
            raw_defines[name] = expr

    resolved = {}
    in_progress = set()  # Guard against circular references

    def resolve(name):
        if name in resolved:
            return resolved[name]
        if name not in raw_defines or name in in_progress:
            return None
        in_progress.add(name)
        expr = raw_defines[name]
        # Direct integer literal
        try:
            val = int(expr)
            resolved[name] = val
            in_progress.discard(name)
            return val
        except ValueError:
            pass
        # Substitute resolved defines into the expression
        safe_expr = expr
        for _ in range(10):
            changed = False
            for k in list(raw_defines.keys()):
                if k not in resolved and k not in in_progress:
                    resolve(k)
                if k in resolved:
                    new_expr = re.sub(
                        r"\b" + re.escape(k) + r"\b", str(resolved[k]), safe_expr
                    )
                    if new_expr != safe_expr:
                        safe_expr = new_expr
                        changed = True
            if not changed:
                break
        try:
            val = eval(safe_expr, {"__builtins__": {}}, {})
            if isinstance(val, (int, float)):
                resolved[name] = int(val)
                in_progress.discard(name)
                return int(val)
        except Exception:
            pass
        in_progress.discard(name)
        return None

    for name in raw_defines:
        resolve(name)

    return resolved


def extract_original_params(defines):
    """
    Map the resolved #define values to the PIPS parameter names used
    in the storage formula.
    """
    params = {
        "NTARGETS": defines.get("NTARGETS", 3),
        "OFFSETBITS": defines.get("OFFSETBITS", 22),
        "CBITS": defines.get("CBITS", 4),
        "TAGBITS": defines.get("TAGBITS", 16),
        "LHT_LOGSETS": defines.get("LHT_LOGSETS", 10),
        "LHT_NUMWAYS": defines.get("LHT_NUMWAYS", 10),
        "LHT_RPBITS": defines.get("LHT_RPBITS", 3),
        "SCC_LOGSETS": defines.get("SCC_LOGSETS", 5),
        "SCC_NUMWAYS": defines.get("SCC_NUMWAYS", 4),
        "SCC_RPBITS": defines.get("SCC_RPBITS", 2),
        "NSCOUTS": defines.get("NSCOUTS", 4),
    }
    return params


def compute_storage(params):
    """
    Compute the total hardware storage budget in bits for a PIPS
    configuration.

    The storage formula is derived from the C++ source:
      - LHT_ENTRY::size() = NTARGETS * OFFSETBITS + (NTARGETS+1) * CBITS
      - LINE_HISTORY_TABLE::size() = n * (LHT_ENTRY::size() + TAGBITS + rpbits)
        where n = numways << logsets
      - Miscellaneous state:
        * frontline: 58 bits (cache line address = 64 - LOG2_BLOCK_SIZE)
        * prevline:  58 bits
        * scout[NSCOUTS]: NSCOUTS * 58 bits
        * ns (round-robin index): ceil(log2(NSCOUTS)) bits
    """
    ntargets = params["NTARGETS"]
    offsetbits = params["OFFSETBITS"]
    cbits = params["CBITS"]
    tagbits = params["TAGBITS"]
    lht_logsets = params["LHT_LOGSETS"]
    lht_numways = params["LHT_NUMWAYS"]
    lht_rpbits = params["LHT_RPBITS"]
    scc_logsets = params["SCC_LOGSETS"]
    scc_numways = params["SCC_NUMWAYS"]
    scc_rpbits = params["SCC_RPBITS"]
    nscouts = params["NSCOUTS"]

    # Per-entry data bits (shared formula for LHT and SCC entries)
    entry_data_bits = ntargets * offsetbits + (ntargets + 1) * cbits

    # Per-entry total bits including tag and replacement policy
    lht_entry_bits = entry_data_bits + tagbits + lht_rpbits
    scc_entry_bits = entry_data_bits + tagbits + scc_rpbits

    # Number of entries
    lht_entries = (1 << lht_logsets) * lht_numways
    scc_entries = (1 << scc_logsets) * scc_numways

    # Table storage
    lht_bits = lht_entries * lht_entry_bits
    scc_bits = scc_entries * scc_entry_bits

    # Miscellaneous register state
    cache_line_addr_bits = 58  # 64 - LOG2_BLOCK_SIZE (6)
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
    # ── Read inputs ──────────────────────────────────────────────
    with open("/app/pips_prefetcher.cc", "r") as f:
        source = f.read()

    with open("/app/spec.json", "r") as f:
        spec = json.load(f)

    # ── Parse source and extract original parameters ─────────────
    defines = parse_defines(source)
    original_params = extract_original_params(defines)
    original_storage = compute_storage(original_params)

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

    # ── Parameter sweep ──────────────────────────────────────────
    budget_bits = spec["budget_bits"]
    fixed = spec["fixed_params"]
    variable = spec["variable_params"]

    ob_range = range(
        variable["OFFSETBITS"]["min"], variable["OFFSETBITS"]["max"] + 1
    )
    ls_range = range(
        variable["LHT_LOGSETS"]["min"], variable["LHT_LOGSETS"]["max"] + 1
    )
    nw_range = range(
        variable["LHT_NUMWAYS"]["min"], variable["LHT_NUMWAYS"]["max"] + 1
    )

    total_evaluated = 0
    valid_configs = []

    for ob in ob_range:
        for ls in ls_range:
            for nw in nw_range:
                total_evaluated += 1
                params = {
                    "NTARGETS": fixed["NTARGETS"],
                    "OFFSETBITS": ob,
                    "CBITS": fixed["CBITS"],
                    "TAGBITS": fixed["TAGBITS"],
                    "LHT_LOGSETS": ls,
                    "LHT_NUMWAYS": nw,
                    "LHT_RPBITS": fixed["LHT_RPBITS"],
                    "SCC_LOGSETS": fixed["SCC_LOGSETS"],
                    "SCC_NUMWAYS": fixed["SCC_NUMWAYS"],
                    "SCC_RPBITS": fixed["SCC_RPBITS"],
                    "NSCOUTS": fixed["NSCOUTS"],
                }
                storage = compute_storage(params)
                if storage["within_budget"]:
                    lht_entries = storage["lht_entries"]
                    max_reach = 1 << (ob - 1)
                    valid_configs.append(
                        {
                            "offsetbits": ob,
                            "logsets": ls,
                            "numways": nw,
                            "lht_entries": lht_entries,
                            "max_reach": max_reach,
                            "total_bits": storage["total_bits"],
                        }
                    )

    print(f"\nSweep: {len(valid_configs)} valid / {total_evaluated} evaluated")

    # ── Pareto front ─────────────────────────────────────────────
    # For each OFFSETBITS, find the config with maximum lht_entries
    best_per_ob = {}
    for c in valid_configs:
        ob = c["offsetbits"]
        if ob not in best_per_ob or c["lht_entries"] > best_per_ob[ob]["lht_entries"]:
            best_per_ob[ob] = c
        elif c["lht_entries"] == best_per_ob[ob]["lht_entries"]:
            # Among equal-entries configs, prefer higher LOGSETS
            if c["logsets"] > best_per_ob[ob]["logsets"]:
                best_per_ob[ob] = c

    # Sort by lht_entries descending, then max_reach descending
    sorted_candidates = sorted(
        best_per_ob.values(), key=lambda c: (-c["lht_entries"], -c["max_reach"])
    )

    # Sweep to build the Pareto front
    pareto_front = []
    max_reach_seen = -1
    for c in sorted_candidates:
        if c["max_reach"] > max_reach_seen:
            pareto_front.append(c)
            max_reach_seen = c["max_reach"]

    # Compute combined score (harmonic mean) for each Pareto point
    for p in pareto_front:
        e, r = p["lht_entries"], p["max_reach"]
        p["combined_score"] = 2.0 * e * r / (e + r)

    print(f"Pareto front: {len(pareto_front)} points")
    for p in pareto_front:
        print(
            f"  OB={p['offsetbits']:2d}  entries={p['lht_entries']:5d}  "
            f"reach={p['max_reach']:>12d}  score={p['combined_score']:.2f}"
        )

    # ── Best combined metric ─────────────────────────────────────
    best_combined = max(pareto_front, key=lambda p: p["combined_score"])

    print(
        f"\nBest combined: OB={best_combined['offsetbits']}, "
        f"entries={best_combined['lht_entries']}, "
        f"reach={best_combined['max_reach']}, "
        f"score={best_combined['combined_score']:.2f}"
    )

    # ── Write output ─────────────────────────────────────────────
    output = {
        "original_config": {
            "params": original_params,
            **original_storage,
        },
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

    output_file = spec.get("output_file", "/app/results.json")
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to {output_file}")


if __name__ == "__main__":
    main()
