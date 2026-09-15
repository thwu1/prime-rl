"""Generate synthetic industry portfolio data in SQLite database + TOML config."""
import numpy as np
import sqlite3
import os

np.random.seed(42)

N = 10
T = 620

industries = ['nodur', 'durbl', 'manuf', 'enrgy', 'hitec',
              'telcm', 'shops', 'hlth', 'utils', 'other']

sectors = ['consumer', 'consumer', 'industrial', 'energy', 'tech',
           'telecom', 'consumer', 'healthcare', 'utilities', 'other']

mu_monthly = np.array([0.008, 0.005, 0.006, 0.009, 0.010,
                        0.004, 0.007, 0.008, 0.003, 0.005])

corr = np.array([
    [1.00, 0.40, 0.45, 0.25, 0.30, 0.35, 0.50, 0.40, 0.20, 0.35],
    [0.40, 1.00, 0.55, 0.30, 0.45, 0.25, 0.35, 0.30, 0.15, 0.50],
    [0.45, 0.55, 1.00, 0.35, 0.40, 0.30, 0.40, 0.35, 0.20, 0.55],
    [0.25, 0.30, 0.35, 1.00, 0.25, 0.20, 0.25, 0.20, 0.30, 0.30],
    [0.30, 0.45, 0.40, 0.25, 1.00, 0.40, 0.30, 0.35, 0.10, 0.40],
    [0.35, 0.25, 0.30, 0.20, 0.40, 1.00, 0.30, 0.25, 0.25, 0.25],
    [0.50, 0.35, 0.40, 0.25, 0.30, 0.30, 1.00, 0.45, 0.20, 0.35],
    [0.40, 0.30, 0.35, 0.20, 0.35, 0.25, 0.45, 1.00, 0.15, 0.30],
    [0.20, 0.15, 0.20, 0.30, 0.10, 0.25, 0.20, 0.15, 1.00, 0.15],
    [0.35, 0.50, 0.55, 0.30, 0.40, 0.25, 0.35, 0.30, 0.15, 1.00]
])

sigma_monthly = np.array([0.045, 0.065, 0.055, 0.075, 0.070,
                           0.048, 0.050, 0.058, 0.035, 0.060])

cov = np.outer(sigma_monthly, sigma_monthly) * corr
returns = np.random.multivariate_normal(mu_monthly, cov, T)

illiquidity = np.array([0.5, 1.8, 1.0, 2.5, 1.5, 0.8, 0.7, 1.2, 0.3, 1.6])

# Create SQLite database
os.makedirs('/app/data', exist_ok=True)
db_path = '/app/data/market.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Table: monthly_returns (long format — one row per period-industry pair)
c.execute('''CREATE TABLE monthly_returns (
    period INTEGER NOT NULL,
    industry TEXT NOT NULL,
    return_value REAL NOT NULL,
    PRIMARY KEY (period, industry)
)''')

rows = []
for t in range(T):
    for i, ind in enumerate(industries):
        rows.append((t, ind, float(returns[t, i])))
c.executemany('INSERT INTO monthly_returns VALUES (?, ?, ?)', rows)

# Table: industry_info
c.execute('''CREATE TABLE industry_info (
    industry TEXT PRIMARY KEY,
    illiquidity REAL NOT NULL,
    sector TEXT NOT NULL
)''')

for i, ind in enumerate(industries):
    c.execute('INSERT INTO industry_info VALUES (?, ?, ?)',
              (ind, float(illiquidity[i]), sectors[i]))

# Create an index for efficient period-based lookups
c.execute('CREATE INDEX idx_returns_period ON monthly_returns(period)')

conn.commit()
conn.close()

# Write TOML config
toml_content = """\
[backtest]
gamma = 2.0
window_length = 120
beta_default = 50
tc_scale = 10000

[grid_search]
beta_start = 0
beta_end = 200
beta_step = 10
"""

with open('/app/config.toml', 'w') as f:
    f.write(toml_content)

print(f"SQLite database created at {db_path}: {T} periods x {N} industries ({T * N} rows)")
print(f"Config written to /app/config.toml")
