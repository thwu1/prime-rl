#!/usr/bin/env python3
"""Generate HDF5 and SQLite data files for CFD workshop task."""
import csv
import sqlite3
from collections import defaultdict

import h5py
import numpy as np

CSV_PATH = "/tmp/dpw_workshop_results.csv"
HDF5_PATH = "/app/data/workshop.h5"
SQLITE_PATH = "/app/data/grid_metadata.db"

LEVEL_ORDER = {"Coarse": 0, "Medium": 1, "Fine": 2}


def main():
    rows = []
    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    participants = defaultdict(list)
    for row in rows:
        participants[row["participant_id"]].append(row)

    with h5py.File(HDF5_PATH, "w") as hf:
        data_grp = hf.create_group("data")

        for pid in sorted(participants.keys()):
            prows = sorted(participants[pid],
                           key=lambda r: LEVEL_ORDER[r["grid_level"]])

            pg = data_grp.create_group(pid)
            pg.attrs["solver"] = prows[0]["solver"]
            pg.attrs["turbulence_model"] = prows[0]["turbulence_model"]

            forces = np.array([
                [float(r["CL"]), float(r["CD"]), float(r["CM"])]
                for r in prows
            ])
            pg.create_dataset("forces", data=forces)

        meta = hf.create_group("meta")
        meta.attrs["force_columns"] = ["CL", "CD", "CM"]
        meta.attrs["level_order"] = ["Coarse", "Medium", "Fine"]
        meta.attrs["configuration"] = "NASA CRM Wing-Body"

    conn = sqlite3.connect(SQLITE_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE participants (
        participant_id TEXT PRIMARY KEY,
        solver TEXT,
        turbulence_model TEXT
    )""")

    c.execute("""CREATE TABLE grid_specs (
        participant_id TEXT,
        grid_level TEXT,
        grid_nodes INTEGER,
        mach REAL,
        reynolds REAL,
        alpha_deg REAL,
        PRIMARY KEY (participant_id, grid_level)
    )""")

    seen = set()
    for row in rows:
        pid = row["participant_id"]
        if pid not in seen:
            c.execute("INSERT INTO participants VALUES (?, ?, ?)",
                      (pid, row["solver"], row["turbulence_model"]))
            seen.add(pid)
        c.execute("INSERT INTO grid_specs VALUES (?, ?, ?, ?, ?, ?)",
                  (pid, row["grid_level"], int(row["grid_nodes"]),
                   float(row["mach"]), float(row["reynolds"]),
                   float(row["alpha_deg"])))

    conn.commit()
    conn.close()

    print(f"Created {HDF5_PATH} and {SQLITE_PATH}")


if __name__ == "__main__":
    main()
