#!/usr/bin/env python3
"""
Validation script for mesh analysis pipeline output.
Checks /app/mesh_report.json against independently computed expected values.
"""
import json
import math
import os
import sys


def compute_grading_sizes(L, N, R):
    """Independently compute first and last cell sizes for geometric grading."""
    if N <= 1:
        return L, L
    if abs(R - 1.0) < 1e-10:
        d = L / N
        return d, d
    r = R ** (1.0 / (N - 1))
    d_first = L * (r - 1.0) / (r ** N - 1.0)
    d_last = d_first * R
    return d_first, d_last


def main():
    report_path = '/app/mesh_report.json'
    if not os.path.exists(report_path):
        print("FAIL: mesh_report.json not found at /app/mesh_report.json")
        print("Run the pipeline first: python3 /app/pipeline/run.py")
        sys.exit(1)

    with open(report_path) as f:
        report = json.load(f)

    passed = 0
    failed = 0
    total = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed, total
        total += 1
        if condition:
            passed += 1
            print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name} -- {detail}")

    print("=" * 60)
    print("Mesh Analysis Pipeline Validation")
    print("=" * 60)

    # Basic mesh info
    print("\n[Basic Mesh Info]")
    check("num_vertices", report.get("num_vertices") == 24,
          f"expected 24, got {report.get('num_vertices')}")
    check("num_blocks", report.get("num_blocks") == 6,
          f"expected 6, got {report.get('num_blocks')}")
    check("total_cells", report.get("total_cells") == 2560,
          f"expected 2560, got {report.get('total_cells')}")

    # Block cell counts
    print("\n[Block Cell Counts]")
    expected_cells = {0: 256, 1: 768, 2: 128, 3: 384, 4: 256, 5: 768}
    for bid, expected in expected_cells.items():
        block = next((b for b in report.get("blocks", []) if b["id"] == bid), None)
        if block:
            check(f"block_{bid}_cells", block["total_cells"] == expected,
                  f"expected {expected}, got {block['total_cells']}")
        else:
            check(f"block_{bid}_exists", False, "block not found")

    # Adjacency
    print("\n[Block Adjacency]")
    expected_adj = [[0, 1], [0, 2], [1, 3], [2, 3], [2, 4], [3, 5], [4, 5]]
    actual_adj = [sorted(p) for p in report.get("adjacency", [])]
    check("adjacency_count", len(actual_adj) == 7,
          f"expected 7 pairs, got {len(actual_adj)}")
    for pair in expected_adj:
        check(f"adj_{pair[0]}-{pair[1]}", sorted(pair) in actual_adj,
              f"pair {pair} missing")

    # Region classification
    print("\n[Region Classification]")
    for bid in range(6):
        block = next((b for b in report.get("blocks", []) if b["id"] == bid), None)
        if block:
            exp_region = "solid" if bid == 2 else "fluid"
            check(f"block_{bid}_region", block.get("region") == exp_region,
                  f"expected '{exp_region}', got '{block.get('region')}'")

    # Cell sizes from grading
    print("\n[Grading Cell Sizes]")
    # Block 0: simpleGrading y=0.25, L=0.01, N=8
    b0 = next((b for b in report.get("blocks", []) if b["id"] == 0), None)
    if b0:
        ef, el = compute_grading_sizes(0.01, 8, 0.25)
        check("block_0_first_y",
              abs(b0["first_cell_height_y"] - ef) / ef < 0.01,
              f"expected {ef:.6e}, got {b0['first_cell_height_y']:.6e}")
        check("block_0_last_y",
              abs(b0["last_cell_height_y"] - el) / el < 0.01,
              f"expected {el:.6e}, got {b0['last_cell_height_y']:.6e}")

    # Block 2: uniform (R=1), L=0.01, N=8
    b2 = next((b for b in report.get("blocks", []) if b["id"] == 2), None)
    if b2:
        eu = 0.01 / 8.0
        check("block_2_uniform",
              abs(b2["first_cell_height_y"] - eu) < 1e-8,
              f"expected {eu:.6e}, got {b2['first_cell_height_y']:.6e}")

    # Block 1: multi-grading y=((0.4 0.5 5.0)(0.6 0.5 0.2)), L=0.03, N=24
    b1 = next((b for b in report.get("blocks", []) if b["id"] == 1), None)
    if b1:
        ef1, _ = compute_grading_sizes(0.4 * 0.03, round(0.5 * 24), 5.0)
        _, el1 = compute_grading_sizes(0.6 * 0.03, round(0.5 * 24), 0.2)
        check("block_1_mg_first",
              abs(b1["first_cell_height_y"] - ef1) / ef1 < 0.01,
              f"expected {ef1:.6e}, got {b1['first_cell_height_y']:.6e}")
        check("block_1_mg_last",
              abs(b1["last_cell_height_y"] - el1) / el1 < 0.01,
              f"expected {el1:.6e}, got {b1['last_cell_height_y']:.6e}")

    # CHT results
    print("\n[Conjugate Heat Transfer]")
    cht = report.get("cht", {})
    check("cht_solid_block", cht.get("solid_block") == 2,
          f"expected 2, got {cht.get('solid_block')}")
    check("cht_fluid_interface", cht.get("fluid_interface_block") == 3,
          f"expected 3, got {cht.get('fluid_interface_block')}")
    check("cht_interface_temp",
          cht.get("interface_temperature_K") is not None and
          abs(cht["interface_temperature_K"] - 310.0) < 0.1,
          f"expected ~310.0 K, got {cht.get('interface_temperature_K')}")
    check("cht_max_temp",
          cht.get("max_heater_temperature_K") is not None and
          abs(cht["max_heater_temperature_K"] - 310.5) < 0.1,
          f"expected ~310.5 K, got {cht.get('max_heater_temperature_K')}")
    check("cht_heat_flux",
          cht.get("interface_heat_flux_W_m2") is not None and
          abs(cht["interface_heat_flux_W_m2"] - 5000.0) / 5000.0 < 0.01,
          f"expected ~5000 W/m2, got {cht.get('interface_heat_flux_W_m2')}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} checks passed, {failed} failed")
    if failed == 0:
        print("ALL CHECKS PASSED")
    else:
        print(f"WARNING: {failed} check(s) failed -- pipeline has bugs")
    print(f"{'=' * 60}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
