#!/usr/bin/env python3
"""Process cruise data and perform crossover quality control.

Reads WOCE-exchange-format cruise files, computes carbonate system
parameters using the corrected solver, and performs crossover QC
analysis at shared deep-water stations.

"""

import os
import json
import sqlite3
import sys

sys.path.insert(0, "/app")
import importlib
import carbonate_solver
importlib.reload(carbonate_solver)


def parse_cruise_file(filepath):
    """Parse a WOCE-exchange format cruise file.

    Returns (cruise_id, list_of_row_dicts).
    """
    rows = []
    headers = None
    cruise_id = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if line.startswith("#"):
                if "CRUISE:" in line:
                    cruise_id = line.split("CRUISE:")[1].strip()
                continue
            if headers is None:
                headers = line.split("\t")
                continue
            values = line.split("\t")
            if len(values) != len(headers):
                continue
            row = dict(zip(headers, values))
            rows.append(row)

    return cruise_id, rows


def filter_good_data(rows):
    """Filter rows where both TA_FLAG and DIC_FLAG are 2 (good quality)."""
    good = []
    for row in rows:
        ta_flag = int(row.get("TA_FLAG", 9))
        dic_flag = int(row.get("DIC_FLAG", 9))
        if ta_flag == 2 and dic_flag == 2:
            good.append(row)
    return good


def compute_carbonate_params(row):
    """Compute carbonate parameters for a single measurement row."""
    T = float(row["TEMPERATURE_C"])
    S = float(row["SALINITY_PSU"])
    P = float(row["PRESSURE_DBAR"])
    TA = float(row["TA_UMOLKG"])
    DIC = float(row["DIC_UMOLKG"])
    Si = float(row["SILICATE_UMOLKG"])
    PO4 = float(row["PHOSPHATE_UMOLKG"])
    depth = float(row["DEPTH_M"])
    station = row["STATION"]

    result = carbonate_solver.solve(TA, DIC, 1, 2, T, S, P, Si, PO4)

    return {
        "station": station,
        "depth": depth,
        "temperature": T,
        "salinity": S,
        "pressure": P,
        "TA_measured": TA,
        "DIC_measured": DIC,
        "pH_computed": result["pH"],
        "fCO2_computed": result["fCO2"],
        "pCO2_computed": result["pCO2"],
        "CO3_computed": result["CO3"],
        "HCO3_computed": result["HCO3"],
        "OmegaCa": result["OmegaCa"],
        "OmegaAr": result["OmegaAr"],
    }


def main():
    # Read crossover specification
    with open("/app/crossover_spec.json", "r") as f:
        spec = json.load(f)

    offset_variables = spec["offset_variables"]

    # Process all cruise files
    cruise_dir = "/app/cruise_data/"
    all_computations = {}  # cruise_id -> list of computation dicts

    for filename in sorted(os.listdir(cruise_dir)):
        if not filename.endswith(".tsv"):
            continue
        filepath = os.path.join(cruise_dir, filename)
        cruise_id, rows = parse_cruise_file(filepath)
        if cruise_id is None:
            print(f"WARNING: No CRUISE header in {filename}, skipping")
            continue

        good_rows = filter_good_data(rows)
        print(f"  {cruise_id}: {len(rows)} total rows, {len(good_rows)} flag-2 rows")

        computations = []
        for row in good_rows:
            comp = compute_carbonate_params(row)
            comp["cruise_id"] = cruise_id
            computations.append(comp)

        all_computations[cruise_id] = computations

    # Flatten for database
    flat_computations = []
    for cruise_id, comps in all_computations.items():
        flat_computations.extend(comps)

    print(f"\nTotal computations: {len(flat_computations)}")

    # Crossover analysis
    all_offsets = []
    all_adjustments = []

    for xover in spec["crossovers"]:
        cruise_a = xover["cruise_a"]
        station_a = xover["station_a"]
        cruise_b = xover["cruise_b"]
        station_b = xover["station_b"]
        min_depth = xover["min_depth_m"]

        # Get deep data for each crossover station
        data_a = [c for c in all_computations.get(cruise_a, [])
                  if c["station"] == station_a and c["depth"] >= min_depth]
        data_b = [c for c in all_computations.get(cruise_b, [])
                  if c["station"] == station_b and c["depth"] >= min_depth]

        print(f"\nCrossover {cruise_a}/{cruise_b}: "
              f"{len(data_a)} deep samples in {station_a}, "
              f"{len(data_b)} deep samples in {station_b}")

        cruise_pair = f"{cruise_a}/{cruise_b}"

        for var in offset_variables:
            offsets = []
            for da in sorted(data_a, key=lambda x: x["depth"]):
                # Find closest depth match in B
                best = None
                best_dist = float("inf")
                for db in data_b:
                    dist = abs(da["depth"] - db["depth"])
                    if dist < best_dist:
                        best_dist = dist
                        best = db
                if best is not None and best_dist < 200:
                    offsets.append(da[var] - best[var])

            if offsets:
                mean_off = sum(offsets) / len(offsets)
                n = len(offsets)
                all_offsets.append({
                    "cruise_pair": cruise_pair,
                    "variable": var,
                    "mean_offset": mean_off,
                    "n_samples": n,
                })
                all_adjustments.append({
                    "cruise_id": cruise_b,
                    "variable": var,
                    "adjustment": mean_off,
                })
                print(f"  {var}: offset={mean_off:.4f}, n={n}")

    # Write to SQLite
    db_path = "/app/qc_results.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE cruise_computations (
        cruise_id TEXT, station TEXT, depth REAL, temperature REAL,
        salinity REAL, pressure REAL, TA_measured REAL, DIC_measured REAL,
        pH_computed REAL, fCO2_computed REAL, pCO2_computed REAL,
        CO3_computed REAL, HCO3_computed REAL, OmegaCa REAL, OmegaAr REAL
    )""")

    cur.execute("""CREATE TABLE crossover_offsets (
        cruise_pair TEXT, variable TEXT, mean_offset REAL, n_samples INTEGER
    )""")

    cur.execute("""CREATE TABLE adjustments (
        cruise_id TEXT, variable TEXT, adjustment REAL
    )""")

    for c in flat_computations:
        cur.execute("""INSERT INTO cruise_computations VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (c["cruise_id"], c["station"], c["depth"], c["temperature"],
             c["salinity"], c["pressure"], c["TA_measured"], c["DIC_measured"],
             c["pH_computed"], c["fCO2_computed"], c["pCO2_computed"],
             c["CO3_computed"], c["HCO3_computed"], c["OmegaCa"], c["OmegaAr"]))

    for o in all_offsets:
        cur.execute("INSERT INTO crossover_offsets VALUES (?, ?, ?, ?)",
            (o["cruise_pair"], o["variable"], o["mean_offset"], o["n_samples"]))

    for a in all_adjustments:
        cur.execute("INSERT INTO adjustments VALUES (?, ?, ?)",
            (a["cruise_id"], a["variable"], a["adjustment"]))

    conn.commit()
    conn.close()

    print(f"\nQC results written to {db_path}")
    print(f"  Computations: {len(flat_computations)}")
    print(f"  Crossover offsets: {len(all_offsets)}")
    print(f"  Adjustments: {len(all_adjustments)}")


if __name__ == "__main__":
    main()
