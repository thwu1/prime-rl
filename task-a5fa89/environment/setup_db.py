#!/usr/bin/env python3
"""Create a deterministic SQLite database and introduce multiple binary corruptions."""
import sqlite3
import struct
import random
import os

DB_PATH = '/app/evidence.db'
PAGE_SIZE = 8192
SEED = 42


def generate_data():
    """Generate deterministic trading compliance data."""
    random.seed(SEED)

    desks = ['Equity', 'FixedIncome', 'Derivatives', 'Commodities', 'FX']
    traders = []
    for i in range(1, 51):
        risk_limit = round(1000000.0 + random.random() * 99000000.0, 2)
        traders.append((i, f'Trader_{i:03d}', desks[i % 5], risk_limit))

    tickers = [
        'AAPL', 'GOOGL', 'MSFT', 'AMZN', 'META',
        'JPM', 'BAC', 'GS', 'MS', 'WFC',
        'UST10Y', 'UST2Y', 'UST5Y', 'BUND10', 'GILT10',
        'SPX_C4500', 'SPX_P4000', 'VIX_C20', 'NDX_C15000', 'RUT_P2000',
        'ES_FUT', 'NQ_FUT', 'CL_FUT', 'GC_FUT', 'SI_FUT',
        'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'
    ]
    asset_classes = (['Equity'] * 10 + ['Bond'] * 5 + ['Option'] * 5 +
                     ['Future'] * 5 + ['FX'] * 5)
    instruments = []
    for i in range(30):
        ref_price = round(10.0 + random.random() * 990.0, 4)
        instruments.append((i + 1, tickers[i], f'{tickers[i]}_Security',
                           asset_classes[i], ref_price))

    trades = []
    for i in range(1, 2001):
        trader_id = random.randint(1, 50)
        instrument_id = random.randint(1, 30)
        side = 'BUY' if random.random() < 0.5 else 'SELL'
        quantity = random.randint(100, 10000)
        price = round(random.uniform(10.0, 1000.0), 4)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        trade_date = f'2024-{month:02d}-{day:02d}'
        trades.append((i, trader_id, instrument_id, side, quantity, price,
                       trade_date))

    flag_types = ['WASH_TRADE', 'FRONT_RUNNING', 'SPOOFING',
                  'INSIDER', 'CONCENTRATION', 'FAT_FINGER']
    flags = []
    for i in range(1, 301):
        trade_id = random.randint(1, 2000)
        ft = flag_types[random.randint(0, 5)]
        roll = random.random()
        if roll < 0.4:
            sev = 'LOW'
        elif roll < 0.7:
            sev = 'MEDIUM'
        elif roll < 0.9:
            sev = 'HIGH'
        else:
            sev = 'CRITICAL'
        desc_len = 200 + random.randint(0, 300)
        desc = f'Flag {ft} on trade {trade_id}: ' + 'A' * desc_len
        resolved = 1 if random.random() < 0.6 else 0
        flags.append((i, trade_id, ft, sev, desc, resolved))

    return traders, instruments, trades, flags


def create_database(db_path):
    """Create the database with deterministic data and non-default page size."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(f'PRAGMA page_size = {PAGE_SIZE}')
    conn.execute('PRAGMA journal_mode = DELETE')
    c = conn.cursor()

    c.execute('''CREATE TABLE traders (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        desk TEXT NOT NULL,
        risk_limit REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE instruments (
        id INTEGER PRIMARY KEY,
        ticker TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        reference_price REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE trades (
        id INTEGER PRIMARY KEY,
        trader_id INTEGER NOT NULL REFERENCES traders(id),
        instrument_id INTEGER NOT NULL REFERENCES instruments(id),
        side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        trade_date TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE compliance_flags (
        id INTEGER PRIMARY KEY,
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        flag_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
        description TEXT NOT NULL,
        resolved INTEGER NOT NULL DEFAULT 0
    )''')

    traders, instruments, trades, flags = generate_data()

    c.executemany('INSERT INTO traders VALUES (?,?,?,?)', traders)
    c.executemany('INSERT INTO instruments VALUES (?,?,?,?,?)', instruments)
    c.executemany('INSERT INTO trades VALUES (?,?,?,?,?,?,?)', trades)
    c.executemany('INSERT INTO compliance_flags VALUES (?,?,?,?,?,?)', flags)

    conn.commit()
    conn.close()


def corrupt_database(db_path):
    """Introduce 6 specific corruptions: 5 header-level + 1 page-level."""
    # Get trades root page before corrupting
    conn = sqlite3.connect(db_path)
    trades_rootpage = conn.execute(
        "SELECT rootpage FROM sqlite_master WHERE name='trades'"
    ).fetchone()[0]
    conn.close()

    with open(db_path, 'r+b') as f:
        data = bytearray(f.read())

    # === Header corruptions (first 100 bytes) ===

    # 1. Magic header byte 6: 'f' (0x66) -> 'F' (0x46)
    #    Changes "SQLite format 3\0" to "SQLite Format 3\0"
    data[6] = 0x46

    # 2. Page size bytes 16-17: 8192 -> 4096
    #    Forces wrong page boundary interpretation
    struct.pack_into('>H', data, 16, 4096)

    # 3. Reserved bytes per page (byte 20): 0 -> 32
    #    Reduces usable page size, corrupting B-tree cell interpretation
    data[20] = 32

    # 4. Text encoding bytes 56-59: 1 (UTF-8) -> 0 (invalid)
    #    Makes text data uninterpretable
    struct.pack_into('>I', data, 56, 0)

    # 5. File change counter bytes 24-27: original -> 0
    #    Invalidates in-header database size
    struct.pack_into('>I', data, 24, 0)

    # === Page-level corruption ===

    # 6. Zero the B-tree page type byte of the trades table root page
    #    This breaks the B-tree structure for that table
    if trades_rootpage == 1:
        page_type_offset = 100  # page 1 B-tree header starts at offset 100
    else:
        page_type_offset = (trades_rootpage - 1) * PAGE_SIZE
    data[page_type_offset] = 0x00

    with open(db_path, 'wb') as f:
        f.write(data)


if __name__ == '__main__':
    create_database(DB_PATH)
    corrupt_database(DB_PATH)
    print('Database created and corrupted successfully.')
