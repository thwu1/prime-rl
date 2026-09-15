"""
Build the operations database for the stock roll cutting optimization task.
"""
import sqlite3
import os

DB_PATH = "/app/data/operations.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# --- Schema ---
c.execute("""
CREATE TABLE stock_rolls (
    type_id TEXT PRIMARY KEY,
    width_mm INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    inventory INTEGER NOT NULL,
    status TEXT NOT NULL
)
""")

c.execute("""
CREATE TABLE products (
    product_code TEXT PRIMARY KEY,
    description TEXT,
    cut_width_mm INTEGER NOT NULL
)
""")

c.execute("""
CREATE TABLE customer_orders (
    order_id TEXT PRIMARY KEY,
    product_code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    priority TEXT,
    customer TEXT,
    order_date TEXT
)
""")

c.execute("""
CREATE TABLE production_log (
    log_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_code TEXT NOT NULL,
    pieces_produced INTEGER NOT NULL,
    production_date TEXT
)
""")

# --- Stock rolls ---
# SRD is on maintenance and must NOT be used
c.executemany("INSERT INTO stock_rolls VALUES (?, ?, ?, ?, ?)", [
    ("SRA", 6000, 60.0, 50, "available"),
    ("SRB", 9500, 88.0, 40, "available"),
    ("SRC", 12000, 118.0, 12, "available"),
    ("SRD", 15000, 150.0, 25, "maintenance"),
])

# --- Products (10 products) ---
c.executemany("INSERT INTO products VALUES (?, ?, ?)", [
    ("P01", "Narrow trim strip", 550),
    ("P02", "Edge banding roll", 780),
    ("P03", "Base panel narrow", 950),
    ("P04", "Standard width panel", 1150),
    ("P05", "Medium format sheet", 1400),
    ("P06", "Wide format panel", 1700),
    ("P07", "Broad sheet", 2100),
    ("P08", "Extra wide panel", 2600),
    ("P09", "Premium large format", 3300),
    ("P10", "Jumbo panel", 4200),
])

# --- Customer orders ---
# Net demand after production deductions:
#   P01: 35, P02: 28, P03: 25, P04: 22, P05: 30
#   P06: 18, P07: 15, P08: 10, P09: 8, P10: 5
c.executemany(
    "INSERT INTO customer_orders VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        # Active orders
        ("ORD-001", "P01", 30, "active", "standard", "Acme Corp", "2026-05-01"),
        ("ORD-002", "P01", 20, "active", "rush", "BuildRight", "2026-05-03"),
        ("ORD-003", "P02", 35, "active", "standard", "CutMaster", "2026-05-02"),
        ("ORD-004", "P03", 18, "active", "standard", "Acme Corp", "2026-05-04"),
        ("ORD-005", "P03", 15, "active", "rush", "DeltaMfg", "2026-05-05"),
        ("ORD-006", "P04", 30, "active", "standard", "BuildRight", "2026-05-06"),
        ("ORD-007", "P05", 25, "active", "standard", "CutMaster", "2026-05-07"),
        ("ORD-008", "P05", 17, "active", "rush", "EdgeWorks", "2026-05-08"),
        ("ORD-009", "P06", 25, "active", "standard", "Acme Corp", "2026-05-09"),
        ("ORD-010", "P07", 20, "active", "standard", "DeltaMfg", "2026-05-10"),
        ("ORD-011", "P08", 15, "active", "standard", "BuildRight", "2026-05-11"),
        ("ORD-012", "P09", 12, "active", "rush", "CutMaster", "2026-05-12"),
        ("ORD-013", "P10", 8, "active", "standard", "EdgeWorks", "2026-05-13"),
        # Cancelled orders (must be excluded from demand)
        ("ORD-014", "P01", 100, "cancelled", "standard", "FabricAll", "2026-04-20"),
        ("ORD-015", "P05", 60, "cancelled", "rush", "GlobalCut", "2026-04-22"),
        ("ORD-016", "P09", 40, "cancelled", "standard", "Acme Corp", "2026-04-25"),
        ("ORD-017", "P10", 25, "cancelled", "standard", "BuildRight", "2026-04-28"),
        # Fulfilled orders (must be excluded from demand)
        ("ORD-018", "P02", 20, "fulfilled", "standard", "DeltaMfg", "2026-03-15"),
        ("ORD-019", "P06", 15, "fulfilled", "rush", "CutMaster", "2026-03-20"),
        ("ORD-020", "P04", 10, "fulfilled", "standard", "Acme Corp", "2026-03-25"),
    ],
)

# --- Production log ---
# Entries for active orders (reduce remaining demand)
c.executemany("INSERT INTO production_log VALUES (?, ?, ?, ?, ?)", [
    ("LOG-001", "ORD-001", "P01", 10, "2026-05-15"),
    ("LOG-002", "ORD-002", "P01", 5,  "2026-05-16"),
    ("LOG-003", "ORD-003", "P02", 7,  "2026-05-17"),
    ("LOG-004", "ORD-004", "P03", 5,  "2026-05-18"),
    ("LOG-005", "ORD-005", "P03", 3,  "2026-05-19"),
    ("LOG-006", "ORD-006", "P04", 8,  "2026-05-20"),
    ("LOG-007", "ORD-007", "P05", 8,  "2026-05-21"),
    ("LOG-008", "ORD-008", "P05", 4,  "2026-05-22"),
    ("LOG-009", "ORD-009", "P06", 7,  "2026-05-23"),
    ("LOG-010", "ORD-010", "P07", 5,  "2026-05-24"),
    ("LOG-011", "ORD-011", "P08", 5,  "2026-05-25"),
    ("LOG-012", "ORD-012", "P09", 4,  "2026-05-26"),
    ("LOG-013", "ORD-013", "P10", 3,  "2026-05-27"),
    # Production for CANCELLED orders -- trap: must not subtract from active demand
    ("LOG-014", "ORD-014", "P01", 25, "2026-04-28"),
    ("LOG-015", "ORD-016", "P09", 10, "2026-04-30"),
    # Production for FULFILLED orders -- should not affect active demand
    ("LOG-016", "ORD-018", "P02", 20, "2026-03-25"),
    ("LOG-017", "ORD-019", "P06", 15, "2026-03-28"),
    ("LOG-018", "ORD-020", "P04", 10, "2026-03-30"),
])

conn.commit()
conn.close()
print("Database created at", DB_PATH)
