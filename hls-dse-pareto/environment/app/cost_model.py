"""
HLS Cost Model for Design Space Exploration.

This module provides functions to evaluate HLS configurations against
benchmark designs, estimating PPA (Power, Performance, Area) metrics.

The model is calibrated against Xilinx Artix-7 xc7a200tffv1156-1 FPGA
characteristics. The Artix-7 200T has:
- 134,600 LUTs
- 269,200 FFs
- 740 DSP48E1 slices
- 365 Block RAM (36Kb each)
"""

import math
from typing import Dict, Any

# Artix-7 200T resource limits
MAX_LUTS = 134600
MAX_FFS = 269200
MAX_DSPS = 740
MAX_BRAMS = 365


def check_compilation(design: Dict, config: Dict) -> bool:
    """Check if a configuration compiles successfully.

    Compilation fails if:
    - unroll_factor > base_cycles (can't unroll more than total iterations)
    - array_partition_factor > base_brams + 1 when base_brams > 0
    """
    if config["unroll_factor"] > design["base_cycles"]:
        return False
    if design["base_brams"] > 0 and config["array_partition_factor"] > design["base_brams"] + 1:
        return False
    return True


def check_simulation(design: Dict, config: Dict) -> bool:
    """Check if a configuration passes simulation.

    Simulation fails if:
    - enable_dataflow AND enable_pipeline AND unroll_factor >= 8
      AND pipeline_ii == 1 (resource conflict causes deadlock)
    - allocation_limit_add == 2 AND unroll_factor >= 4
      AND enable_pipeline (over-constrained adders cause wrong results)
    """
    if (config["enable_dataflow"] and config["enable_pipeline"]
            and config["unroll_factor"] >= 8 and config["pipeline_ii"] == 1):
        return False
    if (config["allocation_limit_add"] == 2 and config["unroll_factor"] >= 4
            and config["enable_pipeline"]):
        return False
    return True


def check_synthesis(design: Dict, config: Dict, luts: int, ffs: int,
                    dsps: int, brams: int) -> bool:
    """Check if a configuration is synthesizable on the target FPGA.

    Synthesis fails if any resource exceeds the Artix-7 200T limits.
    """
    if luts > MAX_LUTS or ffs > MAX_FFS or dsps > MAX_DSPS or brams > MAX_BRAMS:
        return False
    return True


def compute_latency(design: Dict, config: Dict) -> float:
    """Compute estimated latency in nanoseconds."""
    cycles = float(design["base_cycles"])

    if config["enable_pipeline"]:
        depth = design["pipeline_depth"]
        cycles = math.ceil(cycles / depth) * config["pipeline_ii"] + depth - 1

    if config["enable_dataflow"]:
        cycles = cycles * 0.65

    cycles = math.ceil(cycles / config["unroll_factor"])

    latency_ns = cycles * config["clock_period_ns"]
    return round(latency_ns, 4)


def compute_luts(design: Dict, config: Dict) -> int:
    """Compute estimated LUT utilization."""
    luts = design["base_luts"] * config["unroll_factor"]

    if design["base_brams"] > 0:
        luts += (config["array_partition_factor"] - 1) * design["base_brams"] * 64

    if config["enable_pipeline"]:
        depth = design["pipeline_depth"]
        luts = int(luts * (1.0 + 0.15 * depth / 4.0))

    if config["enable_dataflow"]:
        luts = int(luts * 1.25)

    if config["allocation_limit_add"] > 0:
        reduction = config["allocation_limit_add"] * int(design["base_luts"] * 0.05)
        luts = max(luts - reduction, design["base_luts"])

    strategy_factors = {
        "Default": 1.0,
        "Performance_Explore": 1.08,
        "Area_Explore": 0.88
    }
    luts = int(luts * strategy_factors[config["vivado_strategy"]])

    return max(luts, 1)


def compute_ffs(design: Dict, config: Dict) -> int:
    """Compute estimated flip-flop utilization."""
    ffs = design["base_ffs"] * config["unroll_factor"]

    if config["enable_pipeline"]:
        depth = design["pipeline_depth"]
        ffs = int(ffs * (1.0 + 0.2 * depth / 4.0))

    if config["dsp_full_reg"]:
        ffs = int(ffs * 1.15)

    strategy_factors = {
        "Default": 1.0,
        "Performance_Explore": 1.05,
        "Area_Explore": 0.92
    }
    ffs = int(ffs * strategy_factors[config["vivado_strategy"]])

    return max(ffs, 1)


def compute_dsps(design: Dict, config: Dict) -> int:
    """Compute estimated DSP slice utilization."""
    dsps = design["base_dsps"] * min(config["unroll_factor"], 4)
    return dsps


def compute_brams(design: Dict, config: Dict) -> int:
    """Compute estimated Block RAM utilization."""
    brams = design["base_brams"]
    if config["array_partition_factor"] > 1:
        brams = max(0, brams - (config["array_partition_factor"] - 1))
    return brams


def compute_power(design: Dict, config: Dict, luts: int, ffs: int) -> float:
    """Compute estimated power consumption in milliwatts."""
    freq_mhz = 1000.0 / config["clock_period_ns"]
    base_freq = 200.0

    base_activity = design["base_luts"] + design["base_ffs"]
    if base_activity == 0:
        activity_ratio = 1.0
    else:
        activity_ratio = (luts + ffs) / base_activity

    power_mw = design["base_power_mw"] * (freq_mhz / base_freq) * math.sqrt(activity_ratio)

    if config["dsp_full_reg"]:
        power_mw *= 1.08

    strategy_power_factors = {
        "Default": 1.0,
        "Performance_Explore": 1.05,
        "Area_Explore": 0.93
    }
    power_mw *= strategy_power_factors[config["vivado_strategy"]]

    return round(power_mw, 4)


def compute_composite_area(luts: int, ffs: int, dsps: int, brams: int) -> int:
    """Compute composite area metric.

    Weighted sum: LUTs + 2*FFs + 128*DSPs + 256*BRAMs
    Weights reflect relative silicon area of each resource type.
    """
    return luts + 2 * ffs + 128 * dsps + 256 * brams


def evaluate_config(design: Dict, config: Dict) -> Dict[str, Any]:
    """Evaluate a single configuration for a design.

    Returns a dictionary with stage pass/fail flags and PPA metrics
    (only populated for configurations that pass all three stages).
    """
    result = {"config": config.copy()}

    # Stage 1: Compilation
    result["compile_pass"] = check_compilation(design, config)
    if not result["compile_pass"]:
        result["sim_pass"] = False
        result["synth_pass"] = False
        return result

    # Stage 2: Simulation
    result["sim_pass"] = check_simulation(design, config)
    if not result["sim_pass"]:
        result["synth_pass"] = False
        return result

    # Compute resources for synthesis check
    luts = compute_luts(design, config)
    ffs = compute_ffs(design, config)
    dsps = compute_dsps(design, config)
    brams = compute_brams(design, config)

    # Stage 3: Synthesis
    result["synth_pass"] = check_synthesis(design, config, luts, ffs, dsps, brams)
    if not result["synth_pass"]:
        return result

    # Compute PPA metrics
    result["latency_ns"] = compute_latency(design, config)
    result["luts"] = luts
    result["ffs"] = ffs
    result["dsps"] = dsps
    result["brams"] = brams
    result["power_mw"] = compute_power(design, config, luts, ffs)
    result["composite_area"] = compute_composite_area(luts, ffs, dsps, brams)

    return result
