#!/usr/bin/env python3
"""
Solver for the RISC-V Pipeline Hazard and Cache Microarchitecture Analysis task.

Reads the SystemVerilog source files to understand the architecture, then:
1. Computes cache geometry from the parameterized formulas in cache.sv
2. Simulates set-associative caches with true LRU replacement
3. Evaluates pipeline hazard stall/flush logic from hazard.sv

"""
import json
import math
import os


def compute_cache_geometry(cfg):
    """
    Applies the formulas from cache.sv:
      LINEBYTELEN = LINELEN/8
      OFFSETLEN   = clog2(LINEBYTELEN)
      NUMSETS     = WAYSIZEINBYTES * 8 / LINELEN
      SETLEN      = clog2(NUMSETS)
      SETTOP      = SETLEN + OFFSETLEN
      TAGLEN      = PA_BITS - SETTOP
    """
    linelen = cfg["lineleninbits"]
    linebytelen = linelen // 8
    offsetlen = int(math.log2(linebytelen))
    numsets = (cfg["waysizeinbytes"] * 8) // linelen
    setlen = int(math.log2(numsets))
    settop = setlen + offsetlen
    taglen = cfg["pa_bits"] - settop
    total_bytes = cfg["numways"] * cfg["waysizeinbytes"]
    return {
        "linebytelen": linebytelen,
        "offsetlen": offsetlen,
        "numsets": numsets,
        "setlen": setlen,
        "settop": settop,
        "taglen": taglen,
        "total_bytes": total_bytes,
    }


class LRUCache:
    """Set-associative cache with true LRU replacement policy."""

    def __init__(self, numways, numsets, linebytelen):
        self.numways = numways
        self.numsets = numsets
        self.linebytelen = linebytelen
        self.offsetlen = int(math.log2(linebytelen))
        self.setlen = int(math.log2(numsets))
        self.settop = self.setlen + self.offsetlen
        # Each set is a list of tags in LRU order (index 0 = MRU)
        self.sets = [[] for _ in range(numsets)]
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def _decompose(self, addr):
        """Decompose address into set index and tag."""
        line_addr = addr >> self.offsetlen
        set_idx = line_addr & ((1 << self.setlen) - 1)
        tag = addr >> self.settop
        return set_idx, tag

    def access(self, addr):
        """Access the cache. Returns True on hit, False on miss."""
        set_idx, tag = self._decompose(addr)
        way_set = self.sets[set_idx]

        # Check for hit
        for i, t in enumerate(way_set):
            if t == tag:
                way_set.pop(i)
                way_set.insert(0, tag)
                self.hits += 1
                return True

        # Miss
        self.misses += 1
        if len(way_set) >= self.numways:
            way_set.pop()  # Evict LRU
            self.evictions += 1
        way_set.insert(0, tag)
        return False


def simulate_cache(cfg, trace):
    """Simulate cache for given config and trace, return stats."""
    geom = compute_cache_geometry(cfg)
    cache = LRUCache(cfg["numways"], geom["numsets"], geom["linebytelen"])
    for addr in trace:
        cache.access(addr)
    return cache


def simulate_fa_cache(total_lines, linebytelen, trace):
    """Fully-associative cache with given number of lines and line size."""
    # FA = 1 set with total_lines ways
    cache = LRUCache(total_lines, 1, linebytelen)
    for addr in trace:
        cache.access(addr)
    return cache


def compute_hazard_outputs(inputs):
    """
    Compute hazard unit outputs from inputs.
    Implements the exact combinational logic from hazard.sv.
    """
    BPWrongE = inputs["BPWrongE"]
    CSRWriteFenceM = inputs["CSRWriteFenceM"]
    RetM = inputs["RetM"]
    TrapM = inputs["TrapM"]
    StructuralStallD = inputs["StructuralStallD"]
    LSUStallM = inputs["LSUStallM"]
    IFUStallF = inputs["IFUStallF"]
    FPUStallD = inputs["FPUStallD"]
    ExternalStall = inputs["ExternalStall"]
    DivBusyE = inputs["DivBusyE"]
    FDivBusyE = inputs["FDivBusyE"]
    wfiM = inputs["wfiM"]
    IntPendingM = inputs["IntPendingM"]

    # WFI logic
    WFIStallM = wfiM and not IntPendingM
    WFIInterruptedM = wfiM and IntPendingM

    # Flush causes
    FlushDCause = TrapM or RetM or CSRWriteFenceM or BPWrongE
    FlushECause = TrapM or RetM or CSRWriteFenceM or (BPWrongE and not (DivBusyE or FDivBusyE))
    FlushMCause = TrapM or RetM or CSRWriteFenceM
    FlushWCause = TrapM and not WFIInterruptedM

    # Stall causes (gated by flush)
    StallDCause = (StructuralStallD or FPUStallD) and not FlushDCause
    StallECause = (DivBusyE or FDivBusyE) and not FlushECause
    StallMCause = WFIStallM and not FlushMCause
    StallWCause = (IFUStallF and not FlushDCause) or (LSUStallM and not FlushWCause) or ExternalStall

    # Stall propagation (each stage stalls if next stage stalls)
    StallW = StallWCause
    StallM = StallMCause or StallW
    StallE = StallECause or StallM
    StallD = StallDCause or StallE
    StallF = StallD  # StallFCause is always 0

    # Detect first non-stalled stage
    LatestUnstalledD = (not StallD) and StallF
    LatestUnstalledE = (not StallE) and StallD
    LatestUnstalledM = (not StallM) and StallE
    LatestUnstalledW = (not StallW) and StallM

    # Flush outputs
    FlushD = LatestUnstalledD or FlushDCause
    FlushE = LatestUnstalledE or FlushECause
    FlushM = LatestUnstalledM or FlushMCause
    FlushW = LatestUnstalledW or FlushWCause

    return {
        "StallF": int(bool(StallF)),
        "StallD": int(bool(StallD)),
        "StallE": int(bool(StallE)),
        "StallM": int(bool(StallM)),
        "StallW": int(bool(StallW)),
        "FlushD": int(bool(FlushD)),
        "FlushE": int(bool(FlushE)),
        "FlushM": int(bool(FlushM)),
        "FlushW": int(bool(FlushW)),
    }


def main():
    # Load inputs
    with open("/app/configs.json") as f:
        configs_data = json.load(f)
    with open("/app/trace.json") as f:
        trace_data = json.load(f)
    with open("/app/scenarios.json") as f:
        scenarios_data = json.load(f)

    configs = configs_data["configs"]
    trace = [int(a, 16) for a in trace_data["accesses"]]
    scenarios = scenarios_data["scenarios"]

    # 1. Cache Geometry
    cache_geometry = {}
    for cfg in configs:
        cache_geometry[cfg["name"]] = compute_cache_geometry(cfg)

    # 2. Cache Simulation
    cache_simulation = {}
    for cfg in configs:
        geom = compute_cache_geometry(cfg)
        cache = simulate_cache(cfg, trace)

        # FA cache for conflict miss calculation
        total_lines = cfg["numways"] * geom["numsets"]
        fa_cache = simulate_fa_cache(total_lines, geom["linebytelen"], trace)
        conflict_misses = cache.misses - fa_cache.misses

        cache_simulation[cfg["name"]] = {
            "hits": cache.hits,
            "misses": cache.misses,
            "miss_rate": round(cache.misses / len(trace), 4),
            "evictions": cache.evictions,
            "conflict_misses": conflict_misses,
        }

    # 3. Hazard Analysis
    hazard_analysis = {}
    for scenario in scenarios:
        cycles = []
        for cycle_inputs in scenario["cycles"]:
            outputs = compute_hazard_outputs(cycle_inputs)
            cycles.append(outputs)
        hazard_analysis[scenario["name"]] = {"cycles": cycles}

    # Write results
    results = {
        "cache_geometry": cache_geometry,
        "cache_simulation": cache_simulation,
        "hazard_analysis": hazard_analysis,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
