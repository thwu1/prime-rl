#!/usr/bin/env python3
"""Validate reservoir simulation output against physical constraints."""
import csv
import json
import math
import os
import sys


def load_params():
    """Load reservoir parameters from NetCDF input file."""
    import netCDF4 as nc
    ds = nc.Dataset("/app/data/reservoir.nc", "r")
    params = {}
    for attr in ds.ncattrs():
        val = ds.getncattr(attr)
        try:
            params[attr] = float(val)
        except (ValueError, TypeError):
            params[attr] = val
    ds.close()
    return params


def load_inflows():
    """Load inflow timeseries from NetCDF input file."""
    import netCDF4 as nc
    ds = nc.Dataset("/app/data/reservoir.nc", "r")
    inflows = [float(x) for x in ds.variables["inflow_cms"][:]]
    ds.close()
    return inflows


def load_results():
    """Load simulation results from CSV output."""
    results = []
    with open("/app/output/results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {}
            for k, v in row.items():
                if k == "date":
                    entry[k] = v
                else:
                    entry[k] = float(v)
            results.append(entry)
    return results


def main():
    failures = []
    passes = []

    # --- Check output files exist ---
    for fname in ["results.csv", "nor_envelope.csv", "sensitivity.json"]:
        path = f"/app/output/{fname}"
        if not os.path.exists(path):
            failures.append(f"FAIL: {fname} not found at {path}")
        else:
            passes.append(f"PASS: {fname} exists")

    if any("not found" in f for f in failures):
        for msg in passes + failures:
            print(msg)
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)

    params = load_params()
    inflows = load_inflows()
    results = load_results()
    cap = float(params["GRanD_CAP_MCM"])
    initial_storage = float(params["initial_storage_MCM"])
    m3ps_to_MCM_day = 86400.0 / 1e6

    # --- Row count ---
    if len(results) != 730:
        failures.append(f"FAIL: Expected 730 result rows, got {len(results)}")
    else:
        passes.append("PASS: Result row count is 730")

    # --- Total mass balance ---
    total_in = sum(q * m3ps_to_MCM_day for q in inflows)
    total_out = sum(r["outflow_cms"] * m3ps_to_MCM_day for r in results)
    final_storage = results[-1]["storage_MCM"]
    mb_err = abs(total_in - total_out - (final_storage - initial_storage))
    rel_err = mb_err / total_in
    if rel_err >= 1e-8:
        failures.append(
            f"FAIL: Total mass balance relative error = {rel_err:.2e} "
            f"(threshold: 1e-8)"
        )
    else:
        passes.append(
            f"PASS: Total mass balance relative error = {rel_err:.2e}"
        )

    # --- Daily mass balance ---
    prev_storage = initial_storage
    daily_errs = []
    for row, q in zip(results, inflows):
        in_mcm = q * m3ps_to_MCM_day
        out_mcm = row["outflow_cms"] * m3ps_to_MCM_day
        delta = row["storage_MCM"] - prev_storage
        err = abs(in_mcm - out_mcm - delta)
        if err >= 1e-8:
            daily_errs.append((row["date"], err))
        prev_storage = row["storage_MCM"]
    if daily_errs:
        failures.append(
            f"FAIL: Daily mass balance errors on {len(daily_errs)} days "
            f"(max: {max(e for _, e in daily_errs):.2e})"
        )
    else:
        passes.append("PASS: Daily mass balance within tolerance")

    # --- Non-negative storage ---
    neg_days = [r["date"] for r in results if r["storage_MCM"] < -1e-12]
    if neg_days:
        failures.append(f"FAIL: Negative storage on {len(neg_days)} days")
    else:
        passes.append("PASS: All storage values non-negative")

    # --- Storage within capacity ---
    over_days = [
        r["date"] for r in results
        if r["storage_MCM"] > cap + 1e-10
    ]
    if over_days:
        failures.append(
            f"FAIL: Storage exceeds capacity on {len(over_days)} days"
        )
    else:
        passes.append("PASS: Storage within capacity bounds")

    # --- Spill only at capacity ---
    bad_spill = [
        r["date"] for r in results
        if r["spill_cms"] > 1e-12 and abs(r["storage_MCM"] - cap) > 1e-8
    ]
    if bad_spill:
        failures.append(
            f"FAIL: Spill without full storage on {len(bad_spill)} days"
        )
    else:
        passes.append("PASS: Spill only occurs at full capacity")

    # --- Outflow decomposition ---
    decomp_err = [
        r["date"] for r in results
        if abs(r["outflow_cms"] - (r["release_cms"] + r["spill_cms"])) > 1e-10
    ]
    if decomp_err:
        failures.append(
            f"FAIL: Outflow != release + spill on {len(decomp_err)} days"
        )
    else:
        passes.append("PASS: Outflow decomposition correct")

    # --- Non-negative flows ---
    for field in ["release_cms", "spill_cms", "outflow_cms"]:
        neg = [r["date"] for r in results if r[field] < -1e-12]
        if neg:
            failures.append(f"FAIL: Negative {field} on {len(neg)} days")
        else:
            passes.append(f"PASS: All {field} values non-negative")

    # --- NOR envelope reference check ---
    try:
        with open("/app/output/nor_envelope.csv") as f:
            nor_rows = list(csv.DictReader(f))

        if len(nor_rows) != 52:
            failures.append(
                f"FAIL: Expected 52 NOR envelope rows, got {len(nor_rows)}"
            )
        else:
            passes.append("PASS: NOR envelope has 52 rows")

        nor_by_week = {int(r["week"]): r for r in nor_rows}
        # Spot-check against independently verified reference values
        ref_checks = [
            (13, "nor_upper_pct", 75.0),
            (13, "nor_lower_pct", 37.0),
            (39, "nor_upper_pct", 65.0),
            (39, "nor_lower_pct", 43.0),
        ]
        for week, field, expected in ref_checks:
            if week in nor_by_week:
                actual = float(nor_by_week[week][field])
                if abs(actual - expected) > 0.01:
                    failures.append(
                        f"FAIL: NOR {field} at week {week}: "
                        f"expected {expected:.1f}, got {actual:.2f}"
                    )
                else:
                    passes.append(
                        f"PASS: NOR {field} at week {week} = {expected:.1f}"
                    )
    except Exception as e:
        failures.append(f"FAIL: Error reading NOR envelope: {e}")

    # --- Sensitivity analysis basic checks ---
    try:
        with open("/app/output/sensitivity.json") as f:
            sens = json.load(f)
        if len(sens) != 6:
            failures.append(
                f"FAIL: Expected 6 sensitivity entries, got {len(sens)}"
            )
        else:
            passes.append("PASS: Sensitivity analysis has 6 entries")
            # Check mass balance for all sensitivity runs
            for entry in sens:
                if entry["mass_balance_relative_error"] >= 1e-8:
                    failures.append(
                        f"FAIL: Sensitivity mass balance error for "
                        f"multiplier {entry['capacity_multiplier']}: "
                        f"{entry['mass_balance_relative_error']:.2e}"
                    )
            # Check spill monotonicity
            vols = [d["total_spill_volume_MCM"] for d in sens]
            for j in range(len(vols) - 1):
                if vols[j] < vols[j + 1] - 1e-6:
                    failures.append(
                        "FAIL: Spill volume not monotonically decreasing "
                        "with capacity"
                    )
                    break
            else:
                passes.append("PASS: Spill volume decreases with capacity")
    except Exception as e:
        failures.append(f"FAIL: Error reading sensitivity analysis: {e}")

    # --- Summary ---
    print("=" * 60)
    for msg in passes:
        print(msg)
    for msg in failures:
        print(msg)
    print("=" * 60)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    else:
        print(f"\nAll {len(passes)} checks PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
