#!/usr/bin/env python3
"""
Generate the ISDA SIMM v2.5 parameter database at /app/simm_params.db.
All calibration values are from the published ISDA SIMM v2.5 methodology.
"""
import sqlite3, os, sys

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "/app/simm_params.db"

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# ── Scalar model parameters ──────────────────────────────────
c.execute("CREATE TABLE model_params (name TEXT PRIMARY KEY, value REAL)")
scalars = {
    "inflation_rw": 63,
    "ccy_basis_rw": 21,
    "ir_hvr": 0.44,
    "ir_vrw": 0.18,
    "sub_curves_corr": 0.99,
    "inflation_corr": 0.37,
    "ccy_basis_spread_corr": 0.01,
    "ir_gamma": 0.24,
    "creditq_vrw": 0.74,
    "base_corr_weight": 10,
    "creditq_corr_same_issuer": 0.93,
    "creditq_corr_diff_issuer": 0.42,
    "creditq_corr_residual": 0.5,
    "creditq_corr_base": 0.24,
    "creditnonq_vrw": 0.74,
    "creditnonq_corr_same": 0.82,
    "creditnonq_corr_diff": 0.27,
    "creditnonq_corr_residual": 0.5,
    "creditnonq_cross_bucket_corr": 0.40,
    "equity_hvr": 0.58,
    "equity_vrw": 0.45,
    "equity_vrw_b12": 0.96,
    "commodity_hvr": 0.69,
    "commodity_vrw": 0.60,
    "fx_hvr": 0.52,
    "fx_vrw": 0.47,
    "fx_vega_corr": 0.5,
}
c.executemany("INSERT INTO model_params VALUES (?,?)", scalars.items())

# ── Currency configuration ───────────────────────────────────
c.execute("""CREATE TABLE currency_config (
    currency TEXT PRIMARY KEY,
    ir_vol_regime TEXT,
    fx_category TEXT
)""")

# IR vol regime: Regular, Low, or High (High also means high FX vol group)
# Currencies not in this table default to High IR vol and Category3 FX
currency_data = [
    # Regular IR vol currencies
    ("USD", "Regular", "Category1"),
    ("EUR", "Regular", "Category1"),
    ("GBP", "Regular", "Category1"),
    ("CHF", "Regular", "Category1"),
    ("AUD", "Regular", "Category1"),
    ("CAD", "Regular", "Category1"),
    ("NZD", "Regular", "Category2"),
    ("SEK", "Regular", "Category2"),
    ("NOK", "Regular", "Category2"),
    ("DKK", "Regular", "Category3"),
    ("HKD", "Regular", "Category2"),
    ("KRW", "Regular", "Category2"),
    ("SGD", "Regular", "Category2"),
    ("TWD", "Regular", "Category3"),
    # Low IR vol
    ("JPY", "Low", "Category1"),
    # High FX vol group (also high IR vol)
    ("BRL", "High", "Category2"),
    ("RUB", "High", "Category2"),
    ("TRY", "High", "Category2"),
    ("ZAR", "High", "Category2"),
    # Category2 currencies with high IR vol but Regular FX vol group
    # Use 'HighIR' so they don't enter HIGH_VOL_FX_CCY list
    ("CNY", "HighIR", "Category2"),
    ("INR", "HighIR", "Category2"),
    ("MXN", "HighIR", "Category2"),
]
c.executemany("INSERT INTO currency_config VALUES (?,?,?)", currency_data)

# ── IR risk weights ──────────────────────────────────────────
c.execute("""CREATE TABLE ir_risk_weights (
    tenor TEXT, vol_regime TEXT, weight REAL,
    PRIMARY KEY (tenor, vol_regime)
)""")

tenors = ["2w","1m","3m","6m","1y","2y","3y","5y","10y","15y","20y","30y"]
rw_reg  = [115, 112, 96, 74, 66, 61, 56, 52, 53, 57, 60, 66]
rw_low  = [ 15,  18,  9, 11, 13, 15, 18, 20, 19, 19, 20, 23]
rw_high = [119,  93, 80, 82, 90, 92, 95, 95, 94, 108, 105, 101]

for i, t in enumerate(tenors):
    c.execute("INSERT INTO ir_risk_weights VALUES (?,?,?)", (t, "Regular", rw_reg[i]))
    c.execute("INSERT INTO ir_risk_weights VALUES (?,?,?)", (t, "Low", rw_low[i]))
    c.execute("INSERT INTO ir_risk_weights VALUES (?,?,?)", (t, "High", rw_high[i]))

# ── IR tenor correlations ────────────────────────────────────
c.execute("""CREATE TABLE ir_tenor_correlations (
    tenor1 TEXT, tenor2 TEXT, correlation REAL,
    PRIMARY KEY (tenor1, tenor2)
)""")

# Each inner list is a column of the symmetric correlation matrix
ir_corr_cols = [
    [1.00, 0.74, 0.63, 0.55, 0.45, 0.36, 0.32, 0.28, 0.23, 0.20, 0.18, 0.16],
    [0.74, 1.00, 0.80, 0.69, 0.52, 0.41, 0.35, 0.29, 0.24, 0.18, 0.17, 0.16],
    [0.63, 0.80, 1.00, 0.85, 0.67, 0.53, 0.45, 0.39, 0.32, 0.24, 0.22, 0.22],
    [0.55, 0.69, 0.85, 1.00, 0.83, 0.71, 0.62, 0.54, 0.45, 0.36, 0.35, 0.33],
    [0.45, 0.52, 0.67, 0.83, 1.00, 0.94, 0.86, 0.78, 0.65, 0.58, 0.55, 0.53],
    [0.36, 0.41, 0.53, 0.71, 0.94, 1.00, 0.95, 0.89, 0.78, 0.72, 0.68, 0.67],
    [0.32, 0.35, 0.45, 0.62, 0.86, 0.95, 1.00, 0.96, 0.87, 0.80, 0.77, 0.74],
    [0.28, 0.29, 0.39, 0.54, 0.78, 0.89, 0.96, 1.00, 0.94, 0.89, 0.86, 0.84],
    [0.23, 0.24, 0.32, 0.45, 0.65, 0.78, 0.87, 0.94, 1.00, 0.97, 0.95, 0.94],
    [0.20, 0.18, 0.24, 0.36, 0.58, 0.72, 0.80, 0.89, 0.97, 1.00, 0.98, 0.98],
    [0.18, 0.17, 0.22, 0.35, 0.55, 0.68, 0.77, 0.86, 0.95, 0.98, 1.00, 0.99],
    [0.16, 0.16, 0.22, 0.33, 0.53, 0.67, 0.74, 0.84, 0.94, 0.98, 0.99, 1.00],
]
# zip(cols) transposes columns→rows; matrix is symmetric
ir_corr_matrix = list(zip(*ir_corr_cols))

for i, t1 in enumerate(tenors):
    for j, t2 in enumerate(tenors):
        c.execute("INSERT INTO ir_tenor_correlations VALUES (?,?,?)",
                  (t1, t2, ir_corr_cols[j][i]))

# ── CreditQ bucket weights ──────────────────────────────────
c.execute("""CREATE TABLE creditq_bucket_weights (
    bucket INTEGER PRIMARY KEY, weight REAL
)""")
cq_rw = {1:75, 2:91, 3:78, 4:55, 5:67, 6:47, 7:187, 8:665,
          9:262, 10:251, 11:172, 12:247, 0:665}
c.executemany("INSERT INTO creditq_bucket_weights VALUES (?,?)", cq_rw.items())

# ── CreditQ cross-bucket correlations ────────────────────────
c.execute("""CREATE TABLE creditq_cross_bucket_corr (
    bucket1 INTEGER, bucket2 INTEGER, correlation REAL,
    PRIMARY KEY (bucket1, bucket2)
)""")

cq_cb_cols = [
    [1.00, 0.36, 0.38, 0.35, 0.37, 0.33, 0.36, 0.31, 0.32, 0.33, 0.32, 0.30],
    [0.36, 1.00, 0.46, 0.44, 0.45, 0.43, 0.33, 0.36, 0.38, 0.39, 0.40, 0.36],
    [0.38, 0.46, 1.00, 0.49, 0.49, 0.47, 0.34, 0.36, 0.41, 0.42, 0.43, 0.39],
    [0.35, 0.44, 0.49, 1.00, 0.48, 0.48, 0.31, 0.34, 0.38, 0.42, 0.41, 0.37],
    [0.37, 0.45, 0.49, 0.48, 1.00, 0.48, 0.33, 0.35, 0.39, 0.42, 0.43, 0.38],
    [0.33, 0.43, 0.47, 0.48, 0.48, 1.00, 0.29, 0.32, 0.36, 0.39, 0.40, 0.35],
    [0.36, 0.33, 0.34, 0.31, 0.33, 0.29, 1.00, 0.28, 0.32, 0.31, 0.30, 0.28],
    [0.31, 0.36, 0.36, 0.34, 0.35, 0.32, 0.28, 1.00, 0.33, 0.34, 0.33, 0.30],
    [0.32, 0.38, 0.41, 0.38, 0.39, 0.36, 0.32, 0.33, 1.00, 0.38, 0.36, 0.34],
    [0.33, 0.39, 0.42, 0.42, 0.42, 0.39, 0.31, 0.34, 0.38, 1.00, 0.38, 0.36],
    [0.32, 0.40, 0.43, 0.41, 0.43, 0.40, 0.30, 0.33, 0.36, 0.38, 1.00, 0.35],
    [0.30, 0.36, 0.39, 0.37, 0.38, 0.35, 0.28, 0.30, 0.34, 0.36, 0.35, 1.00],
]
for i in range(12):
    for j in range(12):
        c.execute("INSERT INTO creditq_cross_bucket_corr VALUES (?,?,?)",
                  (i+1, j+1, cq_cb_cols[j][i]))

# ── CreditNonQ bucket weights ───────────────────────────────
c.execute("""CREATE TABLE creditnonq_bucket_weights (
    bucket INTEGER PRIMARY KEY, weight REAL
)""")
cnq_rw = {1: 280, 2: 1300, 0: 1300}
c.executemany("INSERT INTO creditnonq_bucket_weights VALUES (?,?)", cnq_rw.items())

# ── Equity bucket weights ───────────────────────────────────
c.execute("""CREATE TABLE equity_bucket_weights (
    bucket INTEGER PRIMARY KEY, weight REAL
)""")
eq_rw = {1:26, 2:28, 3:34, 4:28, 5:23, 6:25, 7:29, 8:27,
         9:32, 10:32, 11:18, 12:18, 0:34}
c.executemany("INSERT INTO equity_bucket_weights VALUES (?,?)", eq_rw.items())

# ── Equity intra-bucket correlations ─────────────────────────
c.execute("""CREATE TABLE equity_intra_bucket_corr (
    bucket INTEGER PRIMARY KEY, correlation REAL
)""")
eq_ib = {1:0.18, 2:0.23, 3:0.30, 4:0.26, 5:0.23, 6:0.35,
         7:0.36, 8:0.33, 9:0.19, 10:0.20, 11:0.45, 12:0.45}
c.executemany("INSERT INTO equity_intra_bucket_corr VALUES (?,?)", eq_ib.items())

# ── Equity cross-bucket correlations ─────────────────────────
c.execute("""CREATE TABLE equity_cross_bucket_corr (
    bucket1 INTEGER, bucket2 INTEGER, correlation REAL,
    PRIMARY KEY (bucket1, bucket2)
)""")

eq_cb_cols = [
    [1.00, 0.20, 0.20, 0.20, 0.13, 0.16, 0.16, 0.16, 0.17, 0.12, 0.18, 0.18],
    [0.20, 1.00, 0.25, 0.23, 0.14, 0.17, 0.18, 0.17, 0.19, 0.13, 0.19, 0.19],
    [0.20, 0.25, 1.00, 0.24, 0.13, 0.17, 0.18, 0.16, 0.20, 0.13, 0.18, 0.18],
    [0.20, 0.23, 0.24, 1.00, 0.17, 0.22, 0.22, 0.22, 0.21, 0.16, 0.24, 0.24],
    [0.13, 0.14, 0.13, 0.17, 1.00, 0.27, 0.26, 0.27, 0.15, 0.20, 0.30, 0.30],
    [0.16, 0.17, 0.17, 0.22, 0.27, 1.00, 0.34, 0.33, 0.18, 0.24, 0.38, 0.38],
    [0.16, 0.18, 0.18, 0.22, 0.26, 0.34, 1.00, 0.32, 0.18, 0.24, 0.37, 0.37],
    [0.16, 0.17, 0.16, 0.22, 0.27, 0.33, 0.32, 1.00, 0.18, 0.23, 0.37, 0.37],
    [0.17, 0.19, 0.20, 0.21, 0.15, 0.18, 0.18, 0.18, 1.00, 0.14, 0.20, 0.20],
    [0.12, 0.13, 0.13, 0.16, 0.20, 0.24, 0.24, 0.23, 0.14, 1.00, 0.25, 0.25],
    [0.18, 0.19, 0.18, 0.24, 0.30, 0.38, 0.37, 0.37, 0.20, 0.25, 1.00, 0.45],
    [0.18, 0.19, 0.18, 0.24, 0.30, 0.38, 0.37, 0.37, 0.20, 0.25, 0.45, 1.00],
]
for i in range(12):
    for j in range(12):
        c.execute("INSERT INTO equity_cross_bucket_corr VALUES (?,?,?)",
                  (i+1, j+1, eq_cb_cols[j][i]))

# ── Commodity bucket weights ─────────────────────────────────
c.execute("""CREATE TABLE commodity_bucket_weights (
    bucket INTEGER PRIMARY KEY, weight REAL
)""")
cm_rw = {1:27, 2:29, 3:33, 4:25, 5:35, 6:24, 7:40, 8:53, 9:44,
         10:58, 11:20, 12:21, 13:13, 14:16, 15:13, 16:58, 17:17}
c.executemany("INSERT INTO commodity_bucket_weights VALUES (?,?)", cm_rw.items())

# ── Commodity intra-bucket correlations ──────────────────────
c.execute("""CREATE TABLE commodity_intra_bucket_corr (
    bucket INTEGER PRIMARY KEY, correlation REAL
)""")
cm_ib = {1:0.84, 2:0.98, 3:0.96, 4:0.97, 5:0.98, 6:0.88, 7:0.98,
         8:0.49, 9:0.80, 10:0.46, 11:0.55, 12:0.46, 13:0.66,
         14:0.18, 15:0.21, 16:0.00, 17:0.36}
c.executemany("INSERT INTO commodity_intra_bucket_corr VALUES (?,?)", cm_ib.items())

# ── Commodity cross-bucket correlations ──────────────────────
c.execute("""CREATE TABLE commodity_cross_bucket_corr (
    bucket1 INTEGER, bucket2 INTEGER, correlation REAL,
    PRIMARY KEY (bucket1, bucket2)
)""")

cm_cb_cols = [
    [1.00, 0.33, 0.21, 0.27, 0.29, 0.21, 0.48, 0.16, 0.41, 0.23, 0.18, 0.02, 0.21, 0.19, 0.15, 0.00, 0.24],
    [0.33, 1.00, 0.94, 0.94, 0.89, 0.21, 0.19, 0.13, 0.21, 0.21, 0.41, 0.27, 0.31, 0.29, 0.21, 0.00, 0.60],
    [0.21, 0.94, 1.00, 0.91, 0.85, 0.12, 0.20, 0.09, 0.19, 0.20, 0.36, 0.18, 0.22, 0.23, 0.23, 0.00, 0.54],
    [0.27, 0.94, 0.91, 1.00, 0.84, 0.14, 0.24, 0.13, 0.21, 0.19, 0.39, 0.25, 0.23, 0.27, 0.18, 0.00, 0.59],
    [0.29, 0.89, 0.85, 0.84, 1.00, 0.15, 0.17, 0.09, 0.16, 0.21, 0.38, 0.28, 0.28, 0.27, 0.18, 0.00, 0.55],
    [0.21, 0.21, 0.12, 0.14, 0.15, 1.00, 0.33, 0.53, 0.26, 0.09, 0.21, 0.04, 0.11, 0.10, 0.09, 0.00, 0.24],
    [0.48, 0.19, 0.20, 0.24, 0.17, 0.33, 1.00, 0.31, 0.72, 0.24, 0.14,-0.12, 0.19, 0.14, 0.08, 0.00, 0.24],
    [0.16, 0.13, 0.09, 0.13, 0.09, 0.53, 0.31, 1.00, 0.24, 0.04, 0.13,-0.07, 0.04, 0.06, 0.01, 0.00, 0.16],
    [0.41, 0.21, 0.19, 0.21, 0.16, 0.26, 0.72, 0.24, 1.00, 0.21, 0.18,-0.07, 0.12, 0.12, 0.10, 0.00, 0.21],
    [0.23, 0.21, 0.20, 0.19, 0.21, 0.09, 0.24, 0.04, 0.21, 1.00, 0.14, 0.11, 0.11, 0.10, 0.07, 0.00, 0.14],
    [0.18, 0.41, 0.36, 0.39, 0.38, 0.21, 0.14, 0.13, 0.18, 0.14, 1.00, 0.28, 0.30, 0.25, 0.18, 0.00, 0.38],
    [0.02, 0.27, 0.18, 0.25, 0.28, 0.04,-0.12,-0.07,-0.07, 0.11, 0.28, 1.00, 0.18, 0.18, 0.08, 0.00, 0.21],
    [0.21, 0.31, 0.22, 0.23, 0.28, 0.11, 0.19, 0.04, 0.12, 0.11, 0.30, 0.18, 1.00, 0.34, 0.16, 0.00, 0.34],
    [0.19, 0.29, 0.23, 0.27, 0.27, 0.10, 0.14, 0.06, 0.12, 0.10, 0.25, 0.18, 0.34, 1.00, 0.13, 0.00, 0.26],
    [0.15, 0.21, 0.23, 0.18, 0.18, 0.09, 0.08, 0.01, 0.10, 0.07, 0.18, 0.08, 0.16, 0.13, 1.00, 0.00, 0.21],
    [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 1.00, 0.00],
    [0.24, 0.60, 0.54, 0.59, 0.55, 0.24, 0.24, 0.16, 0.21, 0.14, 0.38, 0.21, 0.34, 0.26, 0.21, 0.00, 1.00],
]
for i in range(17):
    for j in range(17):
        c.execute("INSERT INTO commodity_cross_bucket_corr VALUES (?,?,?)",
                  (i+1, j+1, cm_cb_cols[j][i]))

# ── FX pair weights ──────────────────────────────────────────
c.execute("""CREATE TABLE fx_pair_weights (
    vol_group1 TEXT, vol_group2 TEXT, weight REAL,
    PRIMARY KEY (vol_group1, vol_group2)
)""")
fx_rw = [
    ("Regular", "Regular", 7.4),
    ("Regular", "High", 13.6),
    ("High", "Regular", 13.6),
    ("High", "High", 14.6),
]
c.executemany("INSERT INTO fx_pair_weights VALUES (?,?,?)", fx_rw)

# ── FX pair correlations ─────────────────────────────────────
c.execute("""CREATE TABLE fx_pair_correlations (
    calc_ccy_type TEXT, vol_group1 TEXT, vol_group2 TEXT, correlation REAL,
    PRIMARY KEY (calc_ccy_type, vol_group1, vol_group2)
)""")
fx_corr = [
    ("Regular", "Regular", "Regular", 0.50),
    ("Regular", "Regular", "High", 0.27),
    ("Regular", "High", "Regular", 0.27),
    ("Regular", "High", "High", 0.42),
    ("High", "Regular", "Regular", 0.85),
    ("High", "Regular", "High", 0.54),
    ("High", "High", "Regular", 0.54),
    ("High", "High", "High", 0.50),
]
c.executemany("INSERT INTO fx_pair_correlations VALUES (?,?,?,?)", fx_corr)

# ── Concentration thresholds ─────────────────────────────────
c.execute("""CREATE TABLE concentration_thresholds (
    risk_class TEXT, margin_type TEXT, key TEXT, threshold_millions REAL,
    PRIMARY KEY (risk_class, margin_type, key)
)""")

ct = []
# IR delta
ir_d = {"USD":230, "EUR":230, "GBP":230,
        "AUD":44, "CAD":44, "CHF":44, "DKK":44, "HKD":44,
        "KRW":44, "NOK":44, "NZD":44, "SEK":44, "SGD":44, "TWD":44,
        "JPY":70, "DEFAULT":33}
for k, v in ir_d.items():
    ct.append(("IR", "delta", k, v))

# IR vega
ir_v = {"USD":3300, "EUR":3300, "GBP":3300,
        "AUD":470, "CAD":470, "CHF":470, "DKK":470, "HKD":470,
        "KRW":470, "NOK":470, "NZD":470, "SEK":470, "SGD":470, "TWD":470,
        "JPY":570, "DEFAULT":120}
for k, v in ir_v.items():
    ct.append(("IR", "vega", k, v))

# CreditQ delta (by bucket)
cq_dt = {1:0.91, 2:0.19, 3:0.19, 4:0.19, 5:0.19, 6:0.19,
         7:0.91, 8:0.19, 9:0.19, 10:0.19, 11:0.19, 12:0.19, 0:0.19}
for k, v in cq_dt.items():
    ct.append(("CreditQ", "delta", str(k), v))

# CreditQ vega
ct.append(("CreditQ", "vega", "ALL", 260))

# CreditNonQ delta
cnq_dt = {1:9.5, 2:0.5, 0:0.5}
for k, v in cnq_dt.items():
    ct.append(("CreditNonQ", "delta", str(k), v))

# CreditNonQ vega
ct.append(("CreditNonQ", "vega", "ALL", 145))

# Equity delta (by bucket)
eq_dt = {1:10, 2:10, 3:10, 4:10, 5:21, 6:21, 7:21, 8:21,
         9:1.4, 10:0.6, 11:2100, 12:2100, 0:0.6}
for k, v in eq_dt.items():
    ct.append(("Equity", "delta", str(k), v))

# Equity vega (by bucket)
eq_vt = {1:210, 2:210, 3:210, 4:210, 5:1300, 6:1300, 7:1300, 8:1300,
         9:40, 10:200, 11:5900, 12:5900, 0:40}
for k, v in eq_vt.items():
    ct.append(("Equity", "vega", str(k), v))

# Commodity delta (by bucket)
cm_dt = {1:310, 2:2100, 3:1700, 4:1700, 5:1700, 6:3200, 7:3200,
         8:2700, 9:2700, 10:52, 11:530, 12:1600, 13:100, 14:100,
         15:100, 16:52, 17:4000}
for k, v in cm_dt.items():
    ct.append(("Commodity", "delta", str(k), v))

# Commodity vega (by bucket)
cm_vt = {1:210, 2:2700, 3:290, 4:290, 5:290, 6:5000, 7:5000,
         8:920, 9:920, 10:100, 11:350, 12:720, 13:500, 14:500,
         15:500, 16:65, 17:65}
for k, v in cm_vt.items():
    ct.append(("Commodity", "vega", str(k), v))

# FX delta (by category)
ct.append(("FX", "delta", "Category1", 5100))
ct.append(("FX", "delta", "Category2", 1200))
ct.append(("FX", "delta", "Others", 190))

# FX vega (by category pair)
ct.append(("FX", "vega", "Category1,Category1", 2800))
ct.append(("FX", "vega", "Category1,Category2", 1300))
ct.append(("FX", "vega", "Category1,Category3", 550))
ct.append(("FX", "vega", "Category2,Category2", 490))
ct.append(("FX", "vega", "Category2,Category3", 310))
ct.append(("FX", "vega", "Category3,Category3", 200))

c.executemany("INSERT INTO concentration_thresholds VALUES (?,?,?,?)", ct)

# ── Risk class correlations ──────────────────────────────────
c.execute("""CREATE TABLE risk_class_correlations (
    class1 TEXT, class2 TEXT, correlation REAL,
    PRIMARY KEY (class1, class2)
)""")

rc_names = ["Rates", "CreditQ", "CreditNonQ", "Equity", "Commodity", "FX"]
rc_corr_cols = [
    [1.00, 0.29, 0.13, 0.28, 0.46, 0.32],
    [0.29, 1.00, 0.54, 0.71, 0.52, 0.38],
    [0.13, 0.54, 1.00, 0.46, 0.41, 0.12],
    [0.28, 0.71, 0.46, 1.00, 0.49, 0.35],
    [0.46, 0.52, 0.41, 0.49, 1.00, 0.41],
    [0.32, 0.38, 0.12, 0.35, 0.41, 1.00],
]
for i in range(6):
    for j in range(6):
        c.execute("INSERT INTO risk_class_correlations VALUES (?,?,?)",
                  (rc_names[i], rc_names[j], rc_corr_cols[j][i]))

conn.commit()
conn.close()
print(f"Created {DB_PATH}")
