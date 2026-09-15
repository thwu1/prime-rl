"""Generate deterministic synthetic futures data in SQLite for backtesting."""
import numpy as np
import pandas as pd
import sqlite3
import os

np.random.seed(42)
dates = pd.bdate_range('2012-01-03', '2023-12-29')
n = len(dates)
date_strs = [d.strftime('%Y-%m-%d') for d in dates]


def gbm_prices(n, p0, annual_vol, annual_drift):
    dt = 1.0 / 252
    daily_drift = (annual_drift - 0.5 * annual_vol ** 2) * dt
    daily_vol = annual_vol * np.sqrt(dt)
    log_returns = np.random.normal(daily_drift, daily_vol, n)
    return np.exp(np.log(p0) + np.cumsum(log_returns))


specs = {
    'BOND':      {'p0': 100,  'vol': 0.06, 'drift': 0.01, 'pointsize': 1000, 'currency': 'USD'},
    'EQUITY':    {'p0': 3500, 'vol': 0.18, 'drift': 0.06, 'pointsize': 10, 'currency': 'EUR'},
    'COMMODITY': {'p0': 60,   'vol': 0.30, 'drift': 0.03, 'pointsize': 1000, 'currency': 'USD'},
}

os.makedirs('/app', exist_ok=True)
conn = sqlite3.connect('/app/market.db')

price_rows = []
carry_rows = []

for name, s in specs.items():
    p = gbm_prices(n, s['p0'], s['vol'], s['drift'])
    carry_spread = np.random.normal(0.001, 0.0005, n) * p
    carry_p = p + carry_spread
    for i in range(n):
        price_rows.append((date_strs[i], name, round(float(p[i]), 4)))
        carry_rows.append((date_strs[i], name, round(float(p[i]), 4), round(float(carry_p[i]), 4)))

pd.DataFrame(price_rows, columns=['date', 'instrument', 'price']).to_sql(
    'prices', conn, if_exists='replace', index=False)
pd.DataFrame(carry_rows, columns=['date', 'instrument', 'price', 'carry_price']).to_sql(
    'carry_prices', conn, if_exists='replace', index=False)

# FX rates: EUR/USD
eur_usd = gbm_prices(n, 1.10, 0.08, 0.0)
fx_rows = [(date_strs[i], 'EUR_USD', round(float(eur_usd[i]), 6)) for i in range(n)]
pd.DataFrame(fx_rows, columns=['date', 'pair', 'rate']).to_sql(
    'fx_rates', conn, if_exists='replace', index=False)

# Instrument metadata
pd.DataFrame([
    {'code': 'BOND', 'pointsize': 1000, 'currency': 'USD'},
    {'code': 'EQUITY', 'pointsize': 10, 'currency': 'EUR'},
    {'code': 'COMMODITY', 'pointsize': 1000, 'currency': 'USD'},
]).to_sql('instruments', conn, if_exists='replace', index=False)

# Create indices for query performance
conn.execute("CREATE INDEX IF NOT EXISTS idx_prices ON prices(instrument, date)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_carry ON carry_prices(instrument, date)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_fx ON fx_rates(pair, date)")

conn.commit()
conn.close()
print("SQLite database created at /app/market.db")
