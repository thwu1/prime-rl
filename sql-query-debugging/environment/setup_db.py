#!/usr/bin/env python3
"""Create the trading analytics database with deterministic test data."""

import sqlite3
import math
import os

DB_PATH = '/app/trading.db'


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE traders (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            desk TEXT NOT NULL,
            region TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            certification_level TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            currency TEXT NOT NULL,
            exchange TEXT NOT NULL,
            lot_size INTEGER NOT NULL,
            tick_size REAL NOT NULL
        );

        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            trader_id INTEGER NOT NULL,
            instrument_id INTEGER NOT NULL,
            trade_date TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('BUY', 'SELL')),
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            commission REAL,
            settlement_date TEXT,
            status TEXT NOT NULL CHECK(status IN ('settled', 'pending', 'cancelled')),
            FOREIGN KEY (trader_id) REFERENCES traders(id),
            FOREIGN KEY (instrument_id) REFERENCES instruments(id)
        );

        CREATE TABLE daily_prices (
            instrument_id INTEGER NOT NULL,
            price_date TEXT NOT NULL,
            open_price REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            close_price REAL NOT NULL,
            volume INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (instrument_id, price_date),
            FOREIGN KEY (instrument_id) REFERENCES instruments(id)
        );

        CREATE TABLE risk_limits (
            id INTEGER PRIMARY KEY,
            trader_id INTEGER NOT NULL,
            asset_class TEXT NOT NULL,
            max_position REAL NOT NULL,
            max_daily_loss REAL NOT NULL,
            effective_date TEXT NOT NULL,
            expiry_date TEXT,
            FOREIGN KEY (trader_id) REFERENCES traders(id)
        );
    ''')

    # ---- Traders ----
    traders = [
        (1, 'Alice Chen', 'Equities', 'US', '2018-03-15', 'Level3', 1),
        (2, 'Bob Kumar', 'Equities', 'US', '2021-07-01', 'Level2', 1),
        (3, 'Carol Smith', 'FixedIncome', 'EU', '2016-01-10', 'Level3', 1),
        (4, 'David Lee', 'FX', 'APAC', '2022-01-10', 'Level1', 1),
        (5, 'Eva Mueller', 'FX', 'EU', '2019-06-01', 'Level2', 1),
        (6, 'Frank Zhang', 'Commodities', 'APAC', '2017-09-12', 'Level3', 0),
        (7, 'Grace Park', 'Equities', 'APAC', '2020-04-15', 'Level2', 1),
        (8, 'Henry Wilson', 'FixedIncome', 'US', '2016-02-28', 'Level3', 1),
        (9, 'Irene Costa', 'Commodities', 'EU', '2023-08-01', 'Level1', 1),
        (10, 'James Taylor', 'Equities', 'US', '2014-01-15', 'Level3', 0),
    ]
    c.executemany('INSERT INTO traders VALUES (?,?,?,?,?,?,?)', traders)

    # ---- Instruments ----
    instruments = [
        (1, 'AAPL', 'Apple Inc.', 'Equity', 'USD', 'NASDAQ', 100, 0.01),
        (2, 'MSFT', 'Microsoft Corp.', 'Equity', 'USD', 'NASDAQ', 100, 0.01),
        (3, 'EURUSD', 'Euro/US Dollar', 'FX', 'USD', 'OTC', 100000, 0.0001),
        (4, 'GBPUSD', 'British Pound/USD', 'FX', 'USD', 'OTC', 100000, 0.0001),
        (5, 'UST10Y', 'US 10Y Treasury', 'FixedIncome', 'USD', 'CME', 1000, 0.015625),
        (6, 'GOLD', 'Gold Futures', 'Commodity', 'USD', 'COMEX', 100, 0.10),
        (7, 'OIL', 'Crude Oil Futures', 'Commodity', 'USD', 'NYMEX', 1000, 0.01),
        (8, 'BUND', 'German 10Y Bund', 'FixedIncome', 'EUR', 'EUREX', 1000, 0.01),
    ]
    c.executemany('INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?)', instruments)

    # ---- Trades ----
    # Fields: id, trader_id, instrument_id, trade_date, direction, quantity,
    #         price, commission, settlement_date, status
    trades = [
        # Alice Chen (Equities, US, active)
        (1,  1, 1, '2024-01-15', 'BUY',  100,   185.50,  12.50,  '2024-01-17', 'settled'),
        (2,  1, 1, '2024-02-20', 'SELL',  50,    192.30,  8.00,   '2024-02-22', 'settled'),
        (3,  1, 1, '2024-03-05', 'BUY',  75,    178.90,  None,   '2024-03-07', 'settled'),
        (4,  1, 2, '2024-01-22', 'BUY',  60,    390.00,  10.00,  '2024-01-24', 'settled'),

        # Bob Kumar (Equities, US, active)
        (5,  2, 1, '2024-01-22', 'BUY',  200,   188.00,  15.00,  '2024-01-24', 'settled'),
        (6,  2, 1, '2024-02-14', 'SELL', 200,   195.00,  15.00,  '2024-02-16', 'settled'),
        # Settlement ANOMALY: Fri 3/1 + 2bd = Tue 3/5, but actual = Mon 3/4
        (7,  2, 1, '2024-03-01', 'BUY',  150,   180.50,  10.00,  '2024-03-04', 'settled'),
        (8,  2, 2, '2024-02-06', 'SELL',  40,    405.20,  8.00,   '2024-02-08', 'settled'),

        # Carol Smith (FixedIncome, EU, active)
        (9,  3, 5, '2024-01-10', 'BUY',  500,   98.50,   25.00,  '2024-01-12', 'settled'),
        # Settlement ANOMALY: Thu 2/15 + 2bd = Mon 2/19, but actual = Tue 2/20
        (10, 3, 5, '2024-02-15', 'SELL', 300,   99.20,   20.00,  '2024-02-20', 'settled'),
        (11, 3, 8, '2024-03-12', 'BUY',  200,   132.40,  15.00,  '2024-03-14', 'settled'),

        # David Lee (FX, APAC, active)
        (12, 4, 3, '2024-01-08', 'BUY',  50000, 1.0950,  5.00,   '2024-01-10', 'settled'),
        (13, 4, 3, '2024-02-12', 'SELL', 30000, 1.0820,  5.00,   '2024-02-14', 'settled'),
        (14, 4, 3, '2024-03-18', 'BUY',  20000, 1.0900,  None,   '2024-03-20', 'settled'),
        # Settlement ANOMALY: Thu 1/25 + 2bd = Mon 1/29, but actual = Tue 1/30
        (15, 4, 4, '2024-01-25', 'BUY',  25000, 1.2700,  5.00,   '2024-01-30', 'settled'),

        # Eva Mueller (FX, EU, active)
        (16, 5, 3, '2024-01-16', 'SELL', 40000, 1.0880,  5.00,   '2024-01-18', 'settled'),
        (17, 5, 3, '2024-02-28', 'BUY',  40000, 1.0830,  5.00,   '2024-03-01', 'settled'),
        (18, 5, 4, '2024-03-06', 'SELL', 15000, 1.2650,  5.00,   '2024-03-08', 'settled'),

        # Frank Zhang (Commodities, APAC, INACTIVE)
        # Settlement ANOMALY: Fri 1/5 + 2bd = Tue 1/9, but actual = Mon 1/8
        (19, 6, 6, '2024-01-05', 'BUY',  50,    2050.00, 30.00,  '2024-01-08', 'settled'),
        (20, 6, 6, '2024-02-22', 'SELL',  30,    2030.00, 20.00,  '2024-02-26', 'settled'),

        # Grace Park (Equities, APAC, active)
        (21, 7, 1, '2024-01-29', 'BUY',  80,    191.00,  10.00,  '2024-01-31', 'settled'),
        (22, 7, 1, '2024-03-15', 'SELL',  40,    176.50,  8.00,   '2024-03-19', 'settled'),
        (23, 7, 2, '2024-02-19', 'BUY',  30,    412.50,  None,   '2024-02-21', 'settled'),

        # Henry Wilson (FixedIncome, US, active)
        (24, 8, 5, '2024-01-22', 'BUY',  1000,  97.80,   50.00,  '2024-01-24', 'settled'),
        (25, 8, 5, '2024-03-11', 'SELL', 500,   98.90,   30.00,  '2024-03-13', 'settled'),
        (26, 8, 8, '2024-02-14', 'BUY',  300,   131.80,  20.00,  '2024-02-16', 'settled'),

        # Irene Costa (Commodities, EU, active)
        (27, 9, 6, '2024-02-05', 'BUY',  20,    2035.00, 15.00,  '2024-02-07', 'settled'),
        (28, 9, 6, '2024-03-20', 'SELL',  20,    2180.00, 15.00,  '2024-03-22', 'settled'),
        (29, 9, 7, '2024-01-17', 'BUY',  10,    72.50,   8.00,   '2024-01-19', 'settled'),

        # James Taylor (Equities, US, INACTIVE)
        (30, 10, 1, '2024-01-08', 'BUY',  300,   186.50,  20.00,  '2024-01-10', 'settled'),
        (31, 10, 2, '2024-02-28', 'SELL', 100,   415.00,  12.00,  '2024-03-01', 'settled'),

        # Cancelled trades
        (32, 1,  1, '2024-02-05', 'BUY',  300,   190.00,  20.00,  None, 'cancelled'),
        (33, 4,  3, '2024-03-10', 'SELL', 100000,1.0850,  None,   None, 'cancelled'),
        (34, 6,  6, '2024-03-15', 'BUY',  40,    2100.00, 25.00,  None, 'cancelled'),

        # Pending trades
        (35, 2,  1, '2024-03-28', 'BUY',  100,   175.00,  12.00,  None, 'pending'),
        (36, 5,  3, '2024-03-29', 'SELL', 25000, 1.0790,  5.00,   None, 'pending'),
    ]
    c.executemany('INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)', trades)

    # ---- Daily Prices (March 2024) ----
    march_days = [1, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 25, 26, 27, 28, 29]
    zero_vol_days = {6, 20}  # Volume = 0 on these days (data gaps / holidays)

    price_configs = [
        # (inst_id, base_price, amplitude, trend, base_volume, decimals)
        (1, 180.0, 3.0, -0.05, 2500000, 2),    # AAPL
        (2, 400.0, 5.0, 0.08, 1800000, 2),      # MSFT
        (3, 1.0880, 0.005, 0.0001, 120000, 4),   # EURUSD
        (5, 98.5, 0.5, -0.02, 80000, 4),         # UST10Y
        (6, 2050.0, 30.0, 2.0, 45000, 2),        # GOLD
    ]

    for inst_id, base, amp, trend, base_vol, dec in price_configs:
        for i, day in enumerate(march_days):
            close = round(base + amp * math.sin(i * 0.7) + trend * i, dec)
            high = round(close * 1.005, dec)
            low = round(close * 0.995, dec)
            open_p = round(close + amp * 0.1 * math.cos(i * 1.1), dec)

            if day in zero_vol_days:
                volume = 0
            else:
                volume = max(10000, base_vol + int(base_vol * 0.3 * math.sin(i * 0.9)))

            date_str = f'2024-03-{day:02d}'
            c.execute(
                'INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)',
                (inst_id, date_str, open_p, high, low, close, volume)
            )

    # Erroneous zero-volume entries on a non-trading day (data feed artifact).
    # March 31, 2024 is a Sunday.
    c.execute(
        'INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)',
        (1, '2024-03-31', 177.50, 178.00, 177.00, 177.80, 0)
    )
    c.execute(
        'INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)',
        (2, '2024-03-31', 402.00, 403.00, 401.00, 402.50, 0)
    )

    # ---- Risk Limits ----
    risk_limits = [
        # Current limits for active traders
        (1,  1, 'Equity',      500.0,   5000.0,  '2024-01-01', None),
        (2,  2, 'Equity',      400.0,   8000.0,  '2024-01-01', None),
        (3,  3, 'FixedIncome', 2000.0,  10000.0, '2024-01-01', '2024-02-28'),  # EXPIRED
        (4,  3, 'FixedIncome', 1000.0,  8000.0,  '2024-03-01', None),          # Current for Carol
        (5,  4, 'FX',          200000.0,5000.0,  '2024-01-01', None),
        (6,  5, 'FX',          150000.0,4000.0,  '2024-01-01', None),
        (7,  7, 'Equity',      300.0,   4000.0,  '2024-01-01', None),
        (8,  8, 'FixedIncome', 3000.0,  15000.0, '2024-01-01', None),
        (9,  9, 'Commodity',   200.0,   5000.0,  '2024-01-01', None),
        # Overlapping older limit for Alice (higher max -- trap for non-deduplication)
        (10, 1, 'Equity',      800.0,   10000.0, '2023-06-01', '2024-06-30'),
    ]
    c.executemany('INSERT INTO risk_limits VALUES (?,?,?,?,?,?,?)', risk_limits)

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == '__main__':
    create_db()
