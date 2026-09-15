CREATE TABLE IF NOT EXISTS volatility_forecast (
    step INTEGER PRIMARY KEY,
    conditional_variance REAL NOT NULL,
    annualized_vol REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS regime_state (
    tick INTEGER PRIMARY KEY,
    regime TEXT NOT NULL,
    vol_ratio REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS quoting_decision (
    tick INTEGER PRIMARY KEY,
    bid REAL NOT NULL,
    ask REAL NOT NULL,
    reservation_price REAL NOT NULL,
    bid_size REAL NOT NULL,
    ask_size REAL NOT NULL,
    active INTEGER NOT NULL,
    halt_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS risk_metrics (
    method TEXT PRIMARY KEY,
    var_95_1d REAL NOT NULL,
    var_99_1d REAL NOT NULL,
    var_99_10d REAL NOT NULL,
    cvar_95 REAL NOT NULL,
    portfolio_notional REAL NOT NULL
);
