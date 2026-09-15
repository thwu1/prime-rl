#!/usr/bin/env python3
"""Build the market database from CSV source files."""
import csv
import random
import sqlite3

db = sqlite3.connect("/app/market.db")
cur = db.cursor()

cur.execute("""CREATE TABLE instruments (
    symbol TEXT PRIMARY KEY,
    point_size REAL NOT NULL,
    weight REAL NOT NULL
)""")

cur.execute("""CREATE TABLE daily_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL,
    volume INTEGER,
    open_interest INTEGER,
    PRIMARY KEY(symbol, date),
    FOREIGN KEY(symbol) REFERENCES instruments(symbol)
)""")

cur.execute("""CREATE TABLE trading_rules (
    rule_name TEXT PRIMARY KEY,
    fast_span INTEGER NOT NULL,
    slow_span INTEGER NOT NULL
)""")

cur.execute("""CREATE TABLE forecast_rule_weights (
    symbol TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY(symbol, rule_name),
    FOREIGN KEY(symbol) REFERENCES instruments(symbol),
    FOREIGN KEY(rule_name) REFERENCES trading_rules(rule_name)
)""")

instruments = [
    ("SP500", 50.0, 0.30),
    ("EUROSTOXX", 10.0, 0.25),
    ("US10", 1000.0, 0.25),
    ("GOLD", 100.0, 0.20),
]
cur.executemany("INSERT INTO instruments VALUES (?,?,?)", instruments)

rules = [
    ("ewmac8_32", 8, 32),
    ("ewmac16_64", 16, 64),
    ("ewmac32_128", 32, 128),
]
cur.executemany("INSERT INTO trading_rules VALUES (?,?,?)", rules)

rule_names = ["ewmac8_32", "ewmac16_64", "ewmac32_128"]
symbols = ["SP500", "EUROSTOXX", "US10", "GOLD"]
fw_data = []
for sym in symbols:
    for i, rn in enumerate(rule_names):
        w = 0.334 if i == 1 else 0.333
        fw_data.append((sym, rn, w))
cur.executemany("INSERT INTO forecast_rule_weights VALUES (?,?,?)", fw_data)

random.seed(42)
for inst in symbols:
    with open(f"/tmp/data/{inst}.csv") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append((
                inst,
                row["date"],
                float(row["price"]),
                random.randint(5000, 200000),
                random.randint(50000, 500000),
            ))
        cur.executemany("INSERT INTO daily_prices VALUES (?,?,?,?,?)", rows)

db.commit()
db.close()
