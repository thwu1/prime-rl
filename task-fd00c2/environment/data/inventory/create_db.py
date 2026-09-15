#!/usr/bin/env python3
"""Create the stock inventory SQLite database."""
import sqlite3
import os

DB_PATH = "/app/data/inventory/stock.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""CREATE TABLE stock_rolls (
    roll_type TEXT PRIMARY KEY,
    width_mm INTEGER NOT NULL,
    material TEXT NOT NULL,
    available_count INTEGER
)""")

c.execute("INSERT INTO stock_rolls VALUES ('STD-5600', 5600, 'kraft_base', NULL)")

c.execute("""CREATE TABLE item_catalog (
    product_code TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    nominal_width_mm INTEGER NOT NULL,
    material_grade TEXT,
    notes TEXT
)""")

items = [
    ("P01", "Kraft liner 1520", 1520, "A", None),
    ("P02", "Corrugated medium 1380", 1380, "A", None),
    ("P03", "Fluting 1710", 1710, "B", None),
    ("P04", "Test board 2150", 2150, "A", None),
    ("P05", "Liner board 960", 960, "B", None),
    ("P06", "Heavy kraft 2340", 2340, "A", None),
    ("P07", "White top liner 1090", 1090, "B", None),
    ("P08", "Semi-chem fluting 830", 830, "A", None),
    ("P09", "Recycled liner 1860", 1860, "B", None),
    ("P10", "Lightweight medium 670", 670, "A", None),
    ("P11", "Double wall board 2540", 2540, "A", None),
    ("P12", "Micro flute 410", 410, "B", None),
    ("P13", "High performance liner 1230", 1230, "A", None),
    ("P14", "Single face board 1440", 1440, "B", None),
    ("P15", "Core board 560", 560, "A", None),
    ("P16", "Containerboard 2010", 2010, "A", None),
    ("P17", "Linerboard 750", 750, "B", None),
    ("P18", "Test liner 1150", 1150, "A", None),
    ("P19", "Chipboard 320", 320, "B", None),
    ("P20", "Fluting medium 1640", 1640, "A", None),
    ("P21", "Heavy duty liner 2670", 2670, "A", None),
    ("P22", "Corrugated insert 490", 490, "B", None),
]

for item in items:
    c.execute("INSERT INTO item_catalog VALUES (?, ?, ?, ?, ?)", item)

c.execute("""CREATE VIEW cutting_summary AS
    SELECT product_code, full_name, nominal_width_mm
    FROM item_catalog
    ORDER BY product_code""")

conn.commit()
conn.close()
print("Created stock database at", DB_PATH)
