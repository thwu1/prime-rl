#!/usr/bin/env python3
"""Generate financial data for the DuckDB analytics forensics task."""

import random
from datetime import datetime, timedelta

import duckdb

random.seed(42)

DB_PATH = "/app/warehouse.duckdb"
con = duckdb.connect(DB_PATH)

# ============================================================
# BRANCHES: 50 branches across 5 regions
# ============================================================
regions = ["North", "South", "East", "West", "Central"]
con.execute("""CREATE TABLE branches (
    branch_id INTEGER PRIMARY KEY, branch_name VARCHAR NOT NULL,
    region VARCHAR NOT NULL, country VARCHAR NOT NULL
)""")
branch_data = []
for i in range(50):
    bid = i + 1
    region = regions[i % 5]
    name = f"{region}_{(i // 5) + 1:02d}"
    branch_data.append((bid, name, region, "US"))
con.executemany("INSERT INTO branches VALUES (?,?,?,?)", branch_data)

# ============================================================
# ACCOUNTS: 5000 accounts
# ============================================================
first_names = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
]
last_names = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
]
account_types = ["checking", "savings", "investment", "corporate", "trust"]
risk_levels = ["low", "medium", "high", "critical"]

con.execute("""CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY, holder_name VARCHAR NOT NULL,
    account_type VARCHAR NOT NULL, opened_date DATE NOT NULL,
    branch_id INTEGER NOT NULL, risk_rating VARCHAR NOT NULL
)""")

base_date = datetime(2020, 1, 1)
acct_data = []
for i in range(5000):
    aid = i + 1
    name = f"{first_names[i % 20]} {last_names[(i * 7) % 20]}"
    atype = account_types[i % 5]
    opened = (base_date + timedelta(days=random.randint(0, 1095))).strftime("%Y-%m-%d")
    bid = (i % 50) + 1
    rr = random.choices(risk_levels, weights=[50, 30, 15, 5])[0]
    acct_data.append((aid, name, atype, opened, bid, rr))
for s in range(0, len(acct_data), 1000):
    con.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?)", acct_data[s:s+1000])

# ============================================================
# MARKET DATA: 50 symbols x ~225 trading days (with 10% gaps)
# ============================================================
con.execute("""CREATE TABLE market_data (
    symbol VARCHAR NOT NULL, price_date DATE NOT NULL,
    close_price DOUBLE NOT NULL, volume BIGINT NOT NULL
)""")

symbols = [f"SYM_{i:03d}" for i in range(1, 51)]
base_prices = {s: 50 + random.random() * 450 for s in symbols}

market_rows = []
for sym in symbols:
    price = base_prices[sym]
    d = datetime(2023, 1, 2)
    end_d = datetime(2023, 12, 29)
    while d <= end_d:
        if d.weekday() < 5:
            price *= (1 + random.gauss(0, 0.02))
            price = max(1.0, price)
            if random.random() > 0.10:
                vol = random.randint(10000, 10000000)
                market_rows.append((sym, d.strftime("%Y-%m-%d"),
                                    round(price, 4), vol))
        d += timedelta(days=1)

for s in range(0, len(market_rows), 5000):
    con.executemany("INSERT INTO market_data VALUES (?,?,?,?)",
                    market_rows[s:s+5000])

# ============================================================
# HOLDINGS: accounts 1-2000, various symbols
# ============================================================
con.execute("""CREATE TABLE holdings (
    holding_id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL,
    symbol VARCHAR NOT NULL, quantity INTEGER NOT NULL,
    acquired_date DATE NOT NULL
)""")

holding_data = []
hid = 0
for aid in range(1, 2001):
    n = random.randint(1, 8)
    held = random.sample(symbols, n)
    for sym in held:
        hid += 1
        qty = random.randint(10, 500)
        acq = (datetime(2023, 1, 1) +
               timedelta(days=random.randint(0, 60))).strftime("%Y-%m-%d")
        holding_data.append((hid, aid, sym, qty, acq))

for s in range(0, len(holding_data), 5000):
    con.executemany("INSERT INTO holdings VALUES (?,?,?,?,?)",
                    holding_data[s:s+5000])

# ============================================================
# TRANSACTIONS: 100K random + 90 chain transactions
# ============================================================
con.execute("""CREATE TABLE transactions (
    txn_id INTEGER PRIMARY KEY, from_account INTEGER NOT NULL,
    to_account INTEGER NOT NULL, amount DOUBLE NOT NULL,
    txn_time TIMESTAMP NOT NULL, txn_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL
)""")

txn_types = ["wire", "ach", "internal", "international", "cash"]
statuses = ["completed", "pending", "reversed", "flagged"]
status_wt = [80, 10, 5, 5]
base_txn = datetime(2023, 1, 1)

txn_batch = []
for i in range(100000):
    tid = i + 1
    fa = random.randint(1, 4000)
    ta = random.randint(1, 4000)
    while ta == fa:
        ta = random.randint(1, 4000)
    amt = round(max(1, random.lognormvariate(5, 2)), 2)
    amt = min(amt, 500000)
    tt = base_txn + timedelta(seconds=random.randint(0, 365 * 24 * 3600))
    ttype = random.choice(txn_types)
    status = random.choices(statuses, weights=status_wt)[0]
    txn_batch.append((tid, fa, ta, amt,
                      tt.strftime("%Y-%m-%d %H:%M:%S"), ttype, status))

# Inject 30 chains of 3 hops each, using accounts 4001-4120
chain_base = datetime(2023, 7, 1)
for ci in range(30):
    a1 = 4001 + ci * 4
    a2, a3, a4 = a1 + 1, a1 + 2, a1 + 3
    t0 = chain_base + timedelta(hours=ci * 3)
    for hop, (frm, to_a) in enumerate([(a1, a2), (a2, a3), (a3, a4)]):
        tid = 100001 + ci * 3 + hop
        amt = 10000.0 * (hop + 1)
        tt = t0 + timedelta(minutes=hop * 20)
        txn_batch.append((tid, frm, to_a, amt,
                          tt.strftime("%Y-%m-%d %H:%M:%S"),
                          "wire", "completed"))

txn_batch.sort(key=lambda x: x[0])
for s in range(0, len(txn_batch), 5000):
    con.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)",
                    txn_batch[s:s+5000])

# ============================================================
# ALERTS: 2000 records
# ============================================================
con.execute("""CREATE TABLE alerts (
    alert_id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL,
    alert_time TIMESTAMP NOT NULL, alert_type VARCHAR NOT NULL,
    severity VARCHAR NOT NULL, resolved BOOLEAN NOT NULL
)""")

alert_types = ["suspicious_activity", "large_transfer", "rapid_succession",
               "unusual_pattern", "compliance_flag"]
severities = ["low", "medium", "high", "critical"]

alert_data = []
for i in range(2000):
    alid = i + 1
    aid = random.randint(1, 5000)
    at = base_txn + timedelta(seconds=random.randint(0, 365 * 24 * 3600))
    atype = random.choice(alert_types)
    sev = random.choices(severities, weights=[30, 35, 25, 10])[0]
    resolved = random.random() > 0.3
    alert_data.append((alid, aid, at.strftime("%Y-%m-%d %H:%M:%S"),
                       atype, sev, resolved))
con.executemany("INSERT INTO alerts VALUES (?,?,?,?,?,?)", alert_data)

con.close()
print(f"Database generated: {DB_PATH}")
print(f"  branches:     50 rows")
print(f"  accounts:     5000 rows")
print(f"  market_data:  {len(market_rows)} rows")
print(f"  holdings:     {len(holding_data)} rows")
print(f"  transactions: {len(txn_batch)} rows")
print(f"  alerts:       2000 rows")
