#!/usr/bin/env python3
"""Convert traces CSV into normalized SQLite database."""
import csv
import sqlite3

DB_PATH = "/app/data/profiling.db"
CSV_PATH = "/tmp/traces.csv"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""CREATE TABLE gpu_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_id TEXT NOT NULL UNIQUE,
    driver_version TEXT NOT NULL,
    session_start TEXT NOT NULL,
    pci_bus_id TEXT NOT NULL
)""")

c.execute("""CREATE TABLE kernel_defs (
    kernel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kernel_name TEXT NOT NULL UNIQUE,
    category TEXT
)""")

c.execute("""CREATE TABLE launch_records (
    record_id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES gpu_sessions(session_id),
    kernel_id INTEGER NOT NULL REFERENCES kernel_defs(kernel_id),
    block_size INTEGER NOT NULL,
    registers_per_thread INTEGER NOT NULL,
    shared_mem_bytes INTEGER NOT NULL,
    measured_active_blocks INTEGER NOT NULL,
    measured_occupancy REAL NOT NULL,
    timestamp_offset_ms INTEGER NOT NULL
)""")

c.execute("CREATE INDEX idx_lr_session ON launch_records(session_id)")
c.execute("CREATE INDEX idx_lr_kernel ON launch_records(kernel_id)")

with open(CSV_PATH) as f:
    rows = list(csv.DictReader(f))

gpu_ids = sorted(set(r["gpu_id"] for r in rows))
gpu_map = {}
pci_slots = {"GPU_A": "0000:01:00.0", "GPU_B": "0000:02:00.0",
             "GPU_C": "0000:03:00.0", "GPU_D": "0000:04:00.0",
             "GPU_E": "0000:05:00.0"}
for gid in gpu_ids:
    c.execute(
        "INSERT INTO gpu_sessions (gpu_id, driver_version, session_start, pci_bus_id) VALUES (?,?,?,?)",
        (gid, "560.35.03", "2025-03-14T10:00:00", pci_slots.get(gid, "0000:00:00.0")))
    gpu_map[gid] = c.lastrowid

categories = {
    "lowres": "baseline", "reg": "register_stress",
    "smem": "shared_mem_stress", "combo": "combined_stress",
    "stress": "extreme_stress", "fft": "signal_processing",
    "stencil": "scientific", "matmul": "linear_algebra",
    "conv": "deep_learning",
}
kernel_names = sorted(set(r["kernel"] for r in rows))
kernel_map = {}
for kn in kernel_names:
    cat = next((v for k, v in categories.items() if kn.startswith(k)), "other")
    c.execute("INSERT INTO kernel_defs (kernel_name, category) VALUES (?,?)", (kn, cat))
    kernel_map[kn] = c.lastrowid

for r in rows:
    c.execute(
        """INSERT INTO launch_records
        (record_id, session_id, kernel_id, block_size, registers_per_thread,
         shared_mem_bytes, measured_active_blocks, measured_occupancy, timestamp_offset_ms)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (int(r["row_id"]), gpu_map[r["gpu_id"]], kernel_map[r["kernel"]],
         int(r["block_size"]), int(r["registers_per_thread"]),
         int(r["shared_mem_per_block"]), int(r["active_blocks"]),
         float(r["occupancy"]), int(r["row_id"]) * 150))

conn.commit()
conn.close()
