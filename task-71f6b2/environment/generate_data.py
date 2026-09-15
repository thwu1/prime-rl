#!/usr/bin/env python3
"""Generate SQLite database from asset returns CSV.
Converts monthly return series to price levels and stores in a normalized schema.
"""
import csv
import sqlite3

# Read returns from CSV
dates = []
tickers = []
returns_by_ticker = {}

with open('/tmp/build/asset_returns.csv') as f:
    reader = csv.reader(f)
    header = next(reader)
    tickers = header[1:]  # Skip 'date' column
    for t in tickers:
        returns_by_ticker[t] = []
    for row in reader:
        dates.append(row[0])
        for i, t in enumerate(tickers):
            returns_by_ticker[t].append(float(row[i + 1]))

# Compute prices starting from 100 at one period before first return
base_date = "2013-12-31"
price_dates = [base_date] + dates
prices_by_ticker = {}
for t in tickers:
    prices = [100.0]
    for r in returns_by_ticker[t]:
        prices.append(prices[-1] * (1 + r))
    prices_by_ticker[t] = prices

# Create SQLite database
conn = sqlite3.connect('/app/data/markets.db')
c = conn.cursor()

c.execute('''CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    ticker TEXT UNIQUE NOT NULL,
    asset_class TEXT NOT NULL
)''')

c.execute('''CREATE TABLE price_history (
    date TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    price REAL NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(id),
    PRIMARY KEY (date, asset_id)
)''')

c.execute('CREATE INDEX idx_ph_date ON price_history(date)')
c.execute('CREATE INDEX idx_ph_asset ON price_history(asset_id)')

# Insert assets
asset_classes = {
    'Bonds': 'fixed_income',
    'Equities': 'equity',
    'RealAssets': 'alternative'
}
for i, t in enumerate(tickers):
    c.execute('INSERT INTO assets VALUES (?, ?, ?)',
              (i + 1, t, asset_classes.get(t, 'unknown')))

# Insert prices
for i, t in enumerate(tickers):
    for j, date in enumerate(price_dates):
        c.execute('INSERT INTO price_history VALUES (?, ?, ?)',
                  (date, i + 1, prices_by_ticker[t][j]))

conn.commit()
conn.close()
print(f"Created markets.db with {len(tickers)} assets and {len(price_dates)} price dates")
