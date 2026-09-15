#!/usr/bin/env python3
"""CUDA GEMM shared memory bank conflict analyzer."""
import json
import sqlite3
import ctypes
import os

# Load the compiled C shared library
lib = ctypes.CDLL("/app/src/libbank.so")
lib.compute_bank.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
lib.compute_bank.restype = ctypes.c_int
lib.row_major_addr.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
lib.row_major_addr.restype = ctypes.c_int


def count_conflicts(addresses, element_bytes, bank_width_bytes, num_banks):
    """Count bank conflicts for a single warp access event.

    Returns max(distinct_addresses_per_bank) - 1.
    Broadcasts (same address by multiple threads) count as 1 hit.
    """
    bank_to_addrs = {}
    for addr in addresses:
        bank = lib.compute_bank(addr, element_bytes, bank_width_bytes, num_banks)
        if bank not in bank_to_addrs:
            bank_to_addrs[bank] = set()
        bank_to_addrs[bank].add(addr)
    if not bank_to_addrs:
        return 0
    return max(len(v) for v in bank_to_addrs.values()) - 1


def tile_conflicts(tile_type, warp_size, num_warps, num_banks,
                   bank_width_bytes, BM, BN, BK, TM, TN,
                   element_bytes, skew):
    """Count total bank conflicts for A or B tile during the compute phase."""
    col_threads = BN // TN
    total = 0

    if tile_type == "A":
        stride = BK + skew
        for w in range(num_warps):
            for r in range(TM):
                for k_i in range(BK):
                    addrs = []
                    for t in range(warp_size):
                        tid = w * warp_size + t
                        row_base = (tid // col_threads) * TM
                        addrs.append(
                            lib.row_major_addr(row_base + r, k_i, stride)
                        )
                    total += count_conflicts(
                        addrs, element_bytes, bank_width_bytes, num_banks
                    )
    else:  # B
        stride = BN + skew
        for w in range(num_warps):
            for c in range(TN):
                for k_i in range(BK):
                    addrs = []
                    for t in range(warp_size):
                        tid = w * warp_size + t
                        col_base = (tid % col_threads) * TN
                        addrs.append(
                            lib.row_major_addr(k_i, col_base + c, stride)
                        )
                    total += count_conflicts(
                        addrs, element_bytes, bank_width_bytes, num_banks
                    )
    return total


def find_optimal_skew(tile_type, warp_size, num_warps, num_banks,
                      bank_width_bytes, BM, BN, BK, TM, TN,
                      element_bytes):
    """Find smallest skew in [0, 32] that minimizes conflicts."""
    best_skew = 0
    best_conflicts = tile_conflicts(
        tile_type, warp_size, num_warps, num_banks, bank_width_bytes,
        BM, BN, BK, TM, TN, element_bytes, 0
    )
    for s in range(1, 33):
        c = tile_conflicts(
            tile_type, warp_size, num_warps, num_banks, bank_width_bytes,
            BM, BN, BK, TM, TN, element_bytes, s
        )
        if c < best_conflicts:
            best_skew = s
            best_conflicts = c
            if c == 0:
                break
    return best_skew, best_conflicts


def main():
    # Read kernel configurations from SQLite
    conn = sqlite3.connect("/app/kernels.db")
    conn.row_factory = sqlite3.Row
    hw = conn.execute("SELECT * FROM hardware").fetchone()
    warp_size = hw["warp_size"]
    num_banks = hw["num_banks"]
    bank_width = hw["bank_width_bytes"]

    kernels = conn.execute("SELECT * FROM kernels ORDER BY name").fetchall()
    conn.close()

    scenarios = []
    for k in kernels:
        BM = k["block_tile_m"]
        BN = k["block_tile_n"]
        BK = k["block_tile_k"]
        TM = k["thread_tile_m"]
        TN = k["thread_tile_n"]
        eb = k["element_bytes"]

        num_threads = (BM * BN) // (TM * TN)
        num_warps = num_threads // warp_size

        common = dict(
            warp_size=warp_size, num_warps=num_warps, num_banks=num_banks,
            bank_width_bytes=bank_width, BM=BM, BN=BN, BK=BK,
            TM=TM, TN=TN, element_bytes=eb
        )

        a_no_pad = tile_conflicts("A", **common, skew=0)
        b_no_pad = tile_conflicts("B", **common, skew=0)
        a_skew, a_padded = find_optimal_skew("A", **common)
        b_skew, b_padded = find_optimal_skew("B", **common)

        scenarios.append({
            "name": k["name"],
            "num_threads": num_threads,
            "num_warps": num_warps,
            "a_tile": {
                "dimensions": [BM, BK],
                "conflicts_no_padding": a_no_pad,
                "optimal_skew": a_skew,
                "conflicts_with_padding": a_padded,
            },
            "b_tile": {
                "dimensions": [BK, BN],
                "conflicts_no_padding": b_no_pad,
                "optimal_skew": b_skew,
                "conflicts_with_padding": b_padded,
            },
            "total_conflicts_no_padding": a_no_pad + b_no_pad,
            "total_conflicts_with_padding": a_padded + b_padded,
        })

    # Write JSON output
    with open("/app/results.json", "w") as f:
        json.dump({"scenarios": scenarios}, f, indent=2)

    # Write SQLite output
    db_path = "/app/analysis.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    adb = sqlite3.connect(db_path)
    adb.execute("""CREATE TABLE conflict_analysis (
        kernel_name TEXT PRIMARY KEY,
        num_threads INTEGER,
        num_warps INTEGER,
        a_conflicts_no_padding INTEGER,
        a_optimal_skew INTEGER,
        a_conflicts_with_padding INTEGER,
        b_conflicts_no_padding INTEGER,
        b_optimal_skew INTEGER,
        b_conflicts_with_padding INTEGER,
        total_conflicts_no_padding INTEGER,
        total_conflicts_with_padding INTEGER
    )""")
    for s in scenarios:
        adb.execute(
            "INSERT INTO conflict_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s["name"], s["num_threads"], s["num_warps"],
             s["a_tile"]["conflicts_no_padding"],
             s["a_tile"]["optimal_skew"],
             s["a_tile"]["conflicts_with_padding"],
             s["b_tile"]["conflicts_no_padding"],
             s["b_tile"]["optimal_skew"],
             s["b_tile"]["conflicts_with_padding"],
             s["total_conflicts_no_padding"],
             s["total_conflicts_with_padding"])
        )
    adb.commit()
    adb.close()


if __name__ == "__main__":
    main()
