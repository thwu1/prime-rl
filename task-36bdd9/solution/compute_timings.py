#!/usr/bin/env python3
"""
Compute DDR4 timing parameters by replicating the logic in
Ramulator 2.0's DDR4 device model (src/dram/impl/DDR4.cpp).
"""

import json
import math

# JEDEC tables from DDR4.cpp (constexpr int arrays)
# Indexed by [dq_id][rate_id]
# dq_id:  0=x4, 1=x8, 2=x16
# rate_id: 0=1600, 1=1866, 2=2133, 3=2400, 4=2666, 5=2933, 6=3200
nRRDS_TABLE = [
    [4, 4, 4, 4, 4, 4, 4],      # x4
    [4, 4, 4, 4, 4, 4, 4],      # x8
    [5, 5, 6, 7, 8, 8, 9],      # x16
]

nRRDL_TABLE = [
    [5, 5, 6, 6, 7, 8, 8],      # x4
    [5, 5, 6, 6, 7, 8, 8],      # x8
    [6, 6, 7, 8, 9, 10, 11],    # x16
]

nFAW_TABLE = [
    [16, 16, 16, 16, 16, 16, 16],   # x4
    [20, 22, 23, 26, 28, 31, 34],   # x8
    [28, 28, 32, 36, 40, 44, 48],   # x16
]

# tRFC in nanoseconds, indexed by density_id (0=2Gb, 1=4Gb, 2=8Gb, 3=16Gb)
tRFC_TABLE = [160, 260, 360, 550]
tREFI_BASE_NS = 7800

RATE_TO_ID = {1600: 0, 1866: 1, 2133: 2, 2400: 3, 2666: 4, 2933: 5, 3200: 6}
DQ_TO_ID = {4: 0, 8: 1, 16: 2}
DENSITY_MB_TO_ID = {2048: 0, 4096: 1, 8192: 2, 16384: 3}

TIMING_PRESETS = {
    "DDR4_2400R": {
        "rate": 2400, "nBL": 4, "nCL": 16, "nRCD": 16, "nRP": 16,
        "nRAS": 39, "nRC": 55, "nWR": 18, "nRTP": 9, "nCWL": 12,
        "nCCDS": 4, "nCCDL": 6, "nWTRS": 3, "nWTRL": 9, "nCS": 2,
        "tCK_ps": 833,
    },
    "DDR4_3200W": {
        "rate": 3200, "nBL": 4, "nCL": 20, "nRCD": 20, "nRP": 20,
        "nRAS": 52, "nRC": 72, "nWR": 24, "nRTP": 12, "nCWL": 16,
        "nCCDS": 4, "nCCDL": 8, "nWTRS": 4, "nWTRL": 12, "nCS": 2,
        "tCK_ps": 625,
    },
    "DDR4_1866M": {
        "rate": 1866, "nBL": 4, "nCL": 13, "nRCD": 13, "nRP": 13,
        "nRAS": 32, "nRC": 45, "nWR": 14, "nRTP": 7, "nCWL": 10,
        "nCCDS": 4, "nCCDL": 5, "nWTRS": 3, "nWTRL": 7, "nCS": 2,
        "tCK_ps": 1071,
    },
}

ORG_PRESETS = {
    "DDR4_8Gb_x8":  {"density_mb": 8192, "dq": 8},
    "DDR4_8Gb_x16": {"density_mb": 8192, "dq": 16},
    "DDR4_4Gb_x4":  {"density_mb": 4096, "dq": 4},
}


def jedec_rounding(t_ns: int, tCK_ps: int) -> int:
    """JEDEC rounding: ceiling division of nanoseconds to cycles."""
    return math.ceil(t_ns * 1000 / tCK_ps)


def compute_config(org_name: str, timing_name: str) -> dict:
    org = ORG_PRESETS[org_name]
    tp = TIMING_PRESETS[timing_name]

    dq_id = DQ_TO_ID[org["dq"]]
    rate_id = RATE_TO_ID[tp["rate"]]
    density_id = DENSITY_MB_TO_ID[org["density_mb"]]
    tCK_ps = tp["tCK_ps"]

    # Organization-dependent timings from JEDEC tables
    nRRDS = nRRDS_TABLE[dq_id][rate_id]
    nRRDL = nRRDL_TABLE[dq_id][rate_id]
    nFAW = nFAW_TABLE[dq_id][rate_id]

    # Density-dependent timings
    nRFC = jedec_rounding(tRFC_TABLE[density_id], tCK_ps)
    nREFI = jedec_rounding(tREFI_BASE_NS, tCK_ps)

    # Read latency: m_read_latency = nCL + nBL
    read_latency_cycles = tp["nCL"] + tp["nBL"]

    # Rank-level RD->WR: nCL + nBL + 2 - nCWL
    min_rd_to_wr_rank_cycles = tp["nCL"] + tp["nBL"] + 2 - tp["nCWL"]

    # Rank-level WR->RD (different bank group): nCWL + nBL + nWTRS
    min_wr_to_rd_rank_cycles = tp["nCWL"] + tp["nBL"] + tp["nWTRS"]

    # Bank-group-level WR->RD (same bank group): nCWL + nBL + nWTRL
    min_wr_to_rd_bankgroup_cycles = tp["nCWL"] + tp["nBL"] + tp["nWTRL"]

    # Bank-level ACT->CAS: nRCD
    min_act_to_cas_bank_cycles = tp["nRCD"]

    # Bank-level WR->PRE: nCWL + nBL + nWR
    min_wr_to_pre_bank_cycles = tp["nCWL"] + tp["nBL"] + tp["nWR"]

    return {
        "nRRDS": nRRDS,
        "nRRDL": nRRDL,
        "nFAW": nFAW,
        "nRFC": nRFC,
        "nREFI": nREFI,
        "tCK_ps": tCK_ps,
        "read_latency_cycles": read_latency_cycles,
        "min_rd_to_wr_rank_cycles": min_rd_to_wr_rank_cycles,
        "min_wr_to_rd_rank_cycles": min_wr_to_rd_rank_cycles,
        "min_wr_to_rd_bankgroup_cycles": min_wr_to_rd_bankgroup_cycles,
        "min_act_to_cas_bank_cycles": min_act_to_cas_bank_cycles,
        "min_wr_to_pre_bank_cycles": min_wr_to_pre_bank_cycles,
    }


def main():
    configs = {
        "A": compute_config("DDR4_8Gb_x8", "DDR4_2400R"),
        "B": compute_config("DDR4_8Gb_x16", "DDR4_3200W"),
        "C": compute_config("DDR4_4Gb_x4", "DDR4_1866M"),
    }

    result = {"configs": configs}

    with open("/app/results.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Timing results written to /app/results.json")
    for key, cfg in configs.items():
        print(f"\nConfig {key}:")
        for param, val in cfg.items():
            print(f"  {param}: {val}")


if __name__ == "__main__":
    main()
