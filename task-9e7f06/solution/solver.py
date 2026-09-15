"""
CUDA warptiling kernel autotuning database builder.
Parses nvcc build logs, enumerates valid configs, computes occupancy,
and produces both a SQLite database and JSON analysis output.

"""
import json
import math
import os
import re
import sqlite3
from itertools import product


def load_gpu():
    with open("/app/gpu.json") as f:
        raw = json.load(f)
    return {
        "warp_size": raw["warp_size"],
        "max_threads_per_block": raw["max_threads_per_block"],
        "max_warps_per_sm": raw["max_warps_per_multiprocessor"],
        "max_regs_per_sm": raw["regs_per_multiprocessor"],
        "reg_allocation_unit": raw["register_allocation_unit_size"],
        "max_smem_per_block_bytes": raw["shared_mem_per_block_bytes"],
        "smem_per_sm_bytes": raw["shared_mem_per_multiprocessor_bytes"],
        "smem_allocation_unit_bytes": raw["shared_mem_allocation_unit_bytes"],
        "cuda_runtime_smem_overhead_bytes": raw["runtime_reserved_smem_per_block_bytes"],
    }


def load_search_ranges():
    with open("/app/search_ranges.json") as f:
        return json.load(f)


def load_queries():
    with open("/app/output_schema.json") as f:
        schema = json.load(f)
    return schema["specific_config_queries"]


def parse_build_log():
    """Parse build_output.log to extract register counts per configuration.

    Each build section contains nvcc command line with -D defines and
    multiple ptxas entries. We extract only the sgemmWarptiling kernel's
    register count, filtering out verifyResult and other helper kernels.
    """
    with open("/app/build_output.log") as f:
        content = f.read()

    profiles = []
    sections = re.split(r"=== Profile Build \d+/\d+ ===", content)

    for section in sections[1:]:
        # Extract -D defines from nvcc command line
        defines = {}
        for m in re.finditer(r"-D(\w+)=(\d+)", section):
            defines[m.group(1)] = int(m.group(2))

        if not defines:
            continue

        # Find register count for the sgemmWarptiling entry function only.
        warptiling_match = re.search(
            r"Compiling entry function '[^']*sgemmWarptiling[^']*'.*?"
            r"Used (\d+) registers",
            section,
            re.DOTALL,
        )

        if warptiling_match:
            regs = int(warptiling_match.group(1))
            profiles.append(
                {
                    "NUM_THREADS": defines["NUM_THREADS"],
                    "BM": defines["BM"],
                    "BN": defines["BN"],
                    "BK": defines["BK"],
                    "WM": defines["WM"],
                    "WN": defines["WN"],
                    "WNITER": defines["WNITER"],
                    "TM": defines["TM"],
                    "TN": defines["TN"],
                    "regs": regs,
                }
            )

    return profiles


def derive_register_model(profiles, gpu):
    """Derive the register overhead constant from calibration profiles.

    The register model is: WMITER * WNITER * TM * TN + TM + TN + C
    where C is a constant overhead we need to determine from the kernel
    source register arrays (threadResults, regM, regN) and profiled builds.
    """
    constants = []
    for p in profiles:
        WARPSIZE = gpu["warp_size"]
        WM, WN = p["WM"], p["WN"]
        TM, TN = p["TM"], p["TN"]
        WNITER = p["WNITER"]
        WMITER = (WM * WN) // (WARPSIZE * TM * TN * WNITER)

        computed = WMITER * WNITER * TM * TN + TM + TN
        constants.append(p["regs"] - computed)

    assert len(set(constants)) == 1, f"Inconsistent register model constants: {constants}"
    return constants[0]


def check_constraints(NT, BM, BN, BK, WM, WN, WNITER, TM, TN, gpu):
    WARPSIZE = gpu["warp_size"]

    if NT % WARPSIZE != 0:
        return False, None
    NUM_WARPS = NT // WARPSIZE

    if BN % WN != 0:
        return False, None
    if BM % WM != 0:
        return False, None
    if (BN // WN) * (BM // WM) != NUM_WARPS:
        return False, None
    if (WM * WN) % (WARPSIZE * TM * TN * WNITER) != 0:
        return False, None

    WMITER = (WM * WN) // (WARPSIZE * TM * TN * WNITER)

    if WM % WMITER != 0:
        return False, None
    if WN % WNITER != 0:
        return False, None
    if (NT * 4) % BK != 0:
        return False, None
    if (NT * 4) % BN != 0:
        return False, None
    if BN % (16 * TN) != 0:
        return False, None
    if BM % (16 * TM) != 0:
        return False, None
    if (BM * BK) % (4 * NT) != 0:
        return False, None
    if (BN * BK) % (4 * NT) != 0:
        return False, None

    smem_bytes = (BM * BK + BK * BN) * 4
    if smem_bytes > gpu["max_smem_per_block_bytes"]:
        return False, None
    if NT > gpu["max_threads_per_block"]:
        return False, None

    return True, WMITER


def compute_occupancy(NT, BM, BN, BK, WM, WN, WNITER, TM, TN, WMITER, reg_overhead, gpu):
    WARPSIZE = gpu["warp_size"]
    warps_per_block = NT // WARPSIZE

    regs_per_thread = WMITER * WNITER * TM * TN + TM + TN + reg_overhead
    regs_per_warp_raw = regs_per_thread * WARPSIZE
    allocated_regs_per_warp = (
        math.ceil(regs_per_warp_raw / gpu["reg_allocation_unit"])
        * gpu["reg_allocation_unit"]
    )
    regs_per_block = allocated_regs_per_warp * warps_per_block

    if regs_per_block > 0:
        max_blocks_by_regs = gpu["max_regs_per_sm"] // regs_per_block
    else:
        max_blocks_by_regs = 999

    smem_data_bytes = (BM * BK + BK * BN) * 4
    smem_per_block = smem_data_bytes + gpu["cuda_runtime_smem_overhead_bytes"]
    allocated_smem = (
        math.ceil(smem_per_block / gpu["smem_allocation_unit_bytes"])
        * gpu["smem_allocation_unit_bytes"]
    )

    if allocated_smem > 0:
        max_blocks_by_smem = gpu["smem_per_sm_bytes"] // allocated_smem
    else:
        max_blocks_by_smem = 999

    max_blocks_by_warps = gpu["max_warps_per_sm"] // warps_per_block

    max_blocks = min(max_blocks_by_regs, max_blocks_by_smem, max_blocks_by_warps)
    active_warps = max_blocks * warps_per_block
    occupancy_pct = round(100.0 * active_warps / gpu["max_warps_per_sm"], 2)

    bottlenecks = []
    if max_blocks_by_regs <= max_blocks_by_smem and max_blocks_by_regs <= max_blocks_by_warps:
        bottlenecks.append("registers")
    if max_blocks_by_smem <= max_blocks_by_regs and max_blocks_by_smem <= max_blocks_by_warps:
        bottlenecks.append("smem")
    if max_blocks_by_warps <= max_blocks_by_regs and max_blocks_by_warps <= max_blocks_by_smem:
        bottlenecks.append("warps")

    return {
        "occupancy_pct": occupancy_pct,
        "bottlenecks": sorted(bottlenecks),
        "regs_per_thread": regs_per_thread,
        "smem_data_bytes": smem_data_bytes,
        "smem_allocated_bytes": allocated_smem,
        "max_blocks_by_regs": max_blocks_by_regs,
        "max_blocks_by_smem": max_blocks_by_smem,
        "max_blocks_by_warps": max_blocks_by_warps,
        "max_blocks": max_blocks,
        "active_warps": active_warps,
    }


def create_database(valid_configs):
    """Create the SQLite database with schema, data, and views."""
    db_path = "/app/output/autotune.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE configurations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_threads INTEGER NOT NULL,
            bm INTEGER NOT NULL,
            bn INTEGER NOT NULL,
            bk INTEGER NOT NULL,
            wm INTEGER NOT NULL,
            wn INTEGER NOT NULL,
            wniter INTEGER NOT NULL,
            tm INTEGER NOT NULL,
            tn INTEGER NOT NULL,
            wmiter INTEGER NOT NULL,
            regs_per_thread INTEGER NOT NULL,
            smem_data_bytes INTEGER NOT NULL,
            smem_allocated_bytes INTEGER NOT NULL,
            max_blocks_by_regs INTEGER NOT NULL,
            max_blocks_by_smem INTEGER NOT NULL,
            max_blocks_by_warps INTEGER NOT NULL,
            max_blocks_per_sm INTEGER NOT NULL,
            active_warps INTEGER NOT NULL,
            occupancy_pct REAL NOT NULL,
            UNIQUE(num_threads, bm, bn, bk, wm, wn, wniter, tm, tn)
        )
    """)

    conn.execute("""
        CREATE TABLE bottlenecks (
            config_id INTEGER NOT NULL REFERENCES configurations(id),
            resource TEXT NOT NULL CHECK(resource IN ('registers', 'smem', 'warps')),
            PRIMARY KEY (config_id, resource)
        )
    """)

    conn.execute("CREATE INDEX idx_configs_occupancy ON configurations(occupancy_pct)")

    for cfg in valid_configs:
        cursor = conn.execute(
            """INSERT INTO configurations
            (num_threads, bm, bn, bk, wm, wn, wniter, tm, tn, wmiter,
             regs_per_thread, smem_data_bytes, smem_allocated_bytes,
             max_blocks_by_regs, max_blocks_by_smem, max_blocks_by_warps,
             max_blocks_per_sm, active_warps, occupancy_pct)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cfg["NT"], cfg["BM"], cfg["BN"], cfg["BK"],
                cfg["WM"], cfg["WN"], cfg["WNITER"], cfg["TM"], cfg["TN"],
                cfg["WMITER"], cfg["regs_per_thread"], cfg["smem_data_bytes"],
                cfg["smem_allocated_bytes"], cfg["max_blocks_by_regs"],
                cfg["max_blocks_by_smem"], cfg["max_blocks_by_warps"],
                cfg["max_blocks"], cfg["active_warps"], cfg["occupancy_pct"],
            ),
        )

        config_id = cursor.lastrowid
        for bn_resource in cfg["bottlenecks"]:
            conn.execute(
                "INSERT INTO bottlenecks (config_id, resource) VALUES (?, ?)",
                (config_id, bn_resource),
            )

    # Create views
    conn.execute("""
        CREATE VIEW occupancy_histogram AS
        SELECT
            occupancy_pct,
            COUNT(*) as config_count
        FROM configurations
        GROUP BY occupancy_pct
        ORDER BY occupancy_pct
    """)

    conn.execute("""
        CREATE VIEW bottleneck_distribution AS
        WITH config_resources AS (
            SELECT
                config_id,
                GROUP_CONCAT(resource) as resources,
                COUNT(*) as resource_count
            FROM bottlenecks
            GROUP BY config_id
        )
        SELECT
            CASE
                WHEN resource_count = 1 AND resources = 'registers' THEN 'registers_only'
                WHEN resource_count = 1 AND resources = 'smem' THEN 'smem_only'
                WHEN resource_count = 1 AND resources = 'warps' THEN 'warps_only'
                ELSE 'multiple'
            END as category,
            COUNT(*) as config_count
        FROM config_resources
        GROUP BY category
        ORDER BY category
    """)

    conn.commit()
    conn.close()
    print(f"Database created at {db_path}")


def build_json_output(valid_configs, gpu, reg_overhead, queries):
    """Build the JSON analysis output."""
    total = len(valid_configs)
    max_occ = max(c["occupancy_pct"] for c in valid_configs)
    at_max = sum(1 for c in valid_configs if c["occupancy_pct"] == max_occ)
    above_50 = sum(1 for c in valid_configs if c["occupancy_pct"] > 50.0)

    reg_only = sum(1 for c in valid_configs if c["bottlenecks"] == ["registers"])
    smem_only = sum(1 for c in valid_configs if c["bottlenecks"] == ["smem"])
    warps_only = sum(1 for c in valid_configs if c["bottlenecks"] == ["warps"])
    multiple = total - reg_only - smem_only - warps_only

    occ_hist = {}
    for c in valid_configs:
        key = str(c["occupancy_pct"])
        occ_hist[key] = occ_hist.get(key, 0) + 1

    specific_results = []
    for qcfg in queries:
        NT = qcfg["NUM_THREADS"]
        BM, BN, BK = qcfg["BM"], qcfg["BN"], qcfg["BK"]
        WM, WN = qcfg["WM"], qcfg["WN"]
        WNITER = qcfg["WNITER"]
        TM, TN = qcfg["TM"], qcfg["TN"]

        valid, WMITER = check_constraints(NT, BM, BN, BK, WM, WN, WNITER, TM, TN, gpu)
        if not valid:
            specific_results.append({
                "label": qcfg["label"],
                "valid": False,
                "WMITER": None,
                "occupancy_pct": None,
                "regs_per_thread": None,
                "smem_bytes": None,
                "bottleneck": None,
                "max_blocks_per_sm": None,
            })
        else:
            occ = compute_occupancy(
                NT, BM, BN, BK, WM, WN, WNITER, TM, TN, WMITER, reg_overhead, gpu
            )
            specific_results.append({
                "label": qcfg["label"],
                "valid": True,
                "WMITER": WMITER,
                "occupancy_pct": occ["occupancy_pct"],
                "regs_per_thread": occ["regs_per_thread"],
                "smem_bytes": occ["smem_data_bytes"],
                "bottleneck": occ["bottlenecks"],
                "max_blocks_per_sm": occ["max_blocks"],
            })

    output = {
        "total_valid_configs": total,
        "max_occupancy_pct": max_occ,
        "num_configs_at_max_occupancy": at_max,
        "num_configs_above_50pct_occupancy": above_50,
        "bottleneck_distribution": {
            "registers_only": reg_only,
            "smem_only": smem_only,
            "warps_only": warps_only,
            "multiple": multiple,
        },
        "occupancy_histogram": occ_hist,
        "specific_configs": specific_results,
    }

    with open("/app/output/analysis.json", "w") as f:
        json.dump(output, f, indent=2)
    print("JSON output written to /app/output/analysis.json")


def main():
    gpu = load_gpu()
    params = load_search_ranges()
    queries = load_queries()

    # Parse build log and derive register model
    profiles = parse_build_log()
    print(f"Parsed {len(profiles)} profiles from build log")
    reg_overhead = derive_register_model(profiles, gpu)
    print(f"Derived register overhead constant: {reg_overhead}")

    param_order = ["NUM_THREADS", "BM", "BN", "BK", "WM", "WN", "WNITER", "TM", "TN"]
    ranges = [params[p] for p in param_order]

    valid_configs = []
    for combo in product(*ranges):
        NT, BM, BN, BK, WM, WN, WNITER, TM, TN = combo
        valid, WMITER = check_constraints(NT, BM, BN, BK, WM, WN, WNITER, TM, TN, gpu)
        if valid:
            occ = compute_occupancy(
                NT, BM, BN, BK, WM, WN, WNITER, TM, TN, WMITER, reg_overhead, gpu
            )
            valid_configs.append({
                "NT": NT, "BM": BM, "BN": BN, "BK": BK,
                "WM": WM, "WN": WN, "WNITER": WNITER, "TM": TM, "TN": TN,
                "WMITER": WMITER,
                **occ,
            })

    os.makedirs("/app/output", exist_ok=True)

    create_database(valid_configs)
    build_json_output(valid_configs, gpu, reg_overhead, queries)

    print(f"Analysis complete: {len(valid_configs)} valid configs")


if __name__ == "__main__":
    main()
