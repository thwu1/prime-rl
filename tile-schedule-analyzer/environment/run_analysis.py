#!/usr/bin/env python3
"""Run tile scheduling analysis for GPU matmul kernel optimization.

Analyzes how different tile execution orderings affect L2 cache pressure
and finds the optimal scheduling configuration for the given hardware.
"""
import json
from kernel_sim import TileGrid, L2CacheModel, TileScheduler, HardwareConfig


def main():
    # Matrix configuration
    M, N, K = 4096, 4096, 2048
    BLOCK_M, BLOCK_N, BLOCK_K = 128, 128, 64

    # Initialize components
    grid = TileGrid(M, N, K, BLOCK_M, BLOCK_N, BLOCK_K)
    hw = HardwareConfig("/app/configs/h100.json")
    cache = L2CacheModel(grid.k_tiles)
    scheduler = TileScheduler(hw.num_sms)

    print(f"Grid: {grid.num_pid_m} x {grid.num_pid_n}, K-tiles: {grid.k_tiles}")
    print(f"Total tiles: {grid.total_tiles}")

    # Memory bandwidth analysis
    bif = hw.bytes_in_flight()
    print(f"Bytes in flight: {bif:.0f}")

    # Find optimal tile scheduling
    candidates = [1, 2, 4, 8, 16, 32]
    optimal_g = scheduler.find_optimal_group_size(grid, cache, candidates)
    print(f"Optimal group size: {optimal_g}")

    # Measure cache pressure for baseline vs optimal
    rm_schedule = grid.naive_schedule()
    rm_pressure = cache.max_window_pressure(rm_schedule, hw.num_sms)

    opt_schedule = grid.grouped_schedule(optimal_g)
    opt_pressure = cache.max_window_pressure(opt_schedule, hw.num_sms)

    print(f"Row-major max L2 pressure: {rm_pressure}")
    print(f"Optimal max L2 pressure:   {opt_pressure}")
    print(f"Pressure reduction: {(1 - opt_pressure / rm_pressure) * 100:.1f}%")

    # Write results
    results = {
        "num_pid_m": grid.num_pid_m,
        "num_pid_n": grid.num_pid_n,
        "k_tiles": grid.k_tiles,
        "total_tiles": grid.total_tiles,
        "bytes_in_flight": bif,
        "optimal_group_size": optimal_g,
        "row_major_max_pressure": rm_pressure,
        "optimal_max_pressure": opt_pressure,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nAnalysis written to /app/analysis.json")


if __name__ == "__main__":
    main()
