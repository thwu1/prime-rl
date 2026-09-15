-- PostgreSQL schema for trading analytics database
-- Uses proper PG types (DATE, DOUBLE PRECISION) instead of SQLite TEXT/REAL

CREATE TABLE traders (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    desk TEXT NOT NULL,
    region TEXT NOT NULL,
    hire_date DATE NOT NULL,
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
    tick_size DOUBLE PRECISION NOT NULL
);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    trader_id INTEGER NOT NULL REFERENCES traders(id),
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    trade_date DATE NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('BUY', 'SELL')),
    quantity DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION,
    settlement_date DATE,
    status TEXT NOT NULL CHECK(status IN ('settled', 'pending', 'cancelled'))
);

CREATE TABLE daily_prices (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    price_date DATE NOT NULL,
    open_price DOUBLE PRECISION NOT NULL,
    high_price DOUBLE PRECISION NOT NULL,
    low_price DOUBLE PRECISION NOT NULL,
    close_price DOUBLE PRECISION NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument_id, price_date)
);

CREATE TABLE risk_limits (
    id INTEGER PRIMARY KEY,
    trader_id INTEGER NOT NULL REFERENCES traders(id),
    asset_class TEXT NOT NULL,
    max_position DOUBLE PRECISION NOT NULL,
    max_daily_loss DOUBLE PRECISION NOT NULL,
    effective_date DATE NOT NULL,
    expiry_date DATE
);
