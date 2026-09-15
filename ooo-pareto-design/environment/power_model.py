"""Power estimation model for out-of-order processor configurations.

Estimates total power consumption (dynamic + leakage) based on
microarchitectural parameters and runtime behavior metrics.
Dynamic power depends on pipeline activity and cache stall behavior.
Leakage power scales with transistor count and junction temperature.
"""

import math
import sys

sys.path.insert(0, "/app")
from arch_model import compute_area


def compute_power(width, rob_size, num_int_regs, num_fp_regs,
                  avg_ipc, avg_l1_miss_rate, temperature=350):
    """Estimate total power consumption in arbitrary units.

    Args:
        width: Pipeline width (fetch/decode/rename/issue/writeback/commit).
        rob_size: Number of reorder buffer entries.
        num_int_regs: Number of physical integer registers.
        num_fp_regs: Number of physical floating-point registers.
        avg_ipc: Geometric mean IPC across representative workloads.
        avg_l1_miss_rate: Arithmetic mean L1D cache miss rate across workloads.
        temperature: Junction temperature in Kelvin (default 350K).

    Returns:
        Total estimated power (float), rounded to 4 decimal places.
    """
    V = 0.9   # supply voltage (V)
    f = 1.0   # clock frequency (GHz)

    # --- Dynamic power ---
    # Activity factor: pipeline utilization modulated by width-dependent
    # switching activity of rename/issue/bypass networks
    activity = (avg_ipc / width) + 0.1 * width

    # Cache misses stall the pipeline, reducing effective switching
    stall_factor = 1.0 / (1.0 + 2.0 * avg_l1_miss_rate)

    # Effective switching capacitance of width-dependent pipeline structures
    C_eff = 0.5 * (rob_size + 2.0 * width * width)

    dynamic_power = C_eff * V * V * f * activity * stall_factor

    # --- Leakage power ---
    area = compute_area(width, rob_size, num_int_regs, num_fp_regs)
    k = -0.002  # temperature sensitivity coefficient
    temp_factor = math.exp(k * (temperature - 300))
    leakage_power = 0.001 * area * temp_factor

    return round(dynamic_power + leakage_power, 4)
