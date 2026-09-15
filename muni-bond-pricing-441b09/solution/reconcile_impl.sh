#!/bin/bash

set -e

DB="/app/output/audit.db"
mkdir -p /app/output
rm -f "$DB"

# Create database schema using sqlite3 CLI
sqlite3 "$DB" "
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    security_type TEXT NOT NULL,
    coupon_rate REAL NOT NULL,
    settlement_date TEXT NOT NULL,
    maturity_date TEXT NOT NULL,
    dated_date TEXT NOT NULL,
    first_coupon_date TEXT NOT NULL,
    frequency INTEGER NOT NULL,
    redemption_value REAL NOT NULL,
    compute TEXT NOT NULL,
    yield_input REAL,
    price_input REAL,
    discount_rate REAL
);

CREATE TABLE computed_values (
    trade_id TEXT PRIMARY KEY REFERENCES trades(trade_id),
    accrued_interest REAL,
    dollar_price REAL,
    yield REAL,
    yield_to_worst REAL,
    worst_date TEXT,
    worst_rv REAL
);

CREATE TABLE vendor_values (
    trade_id TEXT PRIMARY KEY REFERENCES trades(trade_id),
    accrued_interest REAL,
    dollar_price REAL,
    yield REAL,
    yield_to_worst REAL,
    worst_date TEXT,
    worst_rv REAL
);

CREATE TABLE discrepancies (
    trade_id TEXT NOT NULL,
    field TEXT NOT NULL,
    vendor_value TEXT,
    correct_value TEXT,
    PRIMARY KEY (trade_id, field)
);

CREATE VIEW validation_summary AS
SELECT trade_id,
    COUNT(*) as num_discrepancies,
    GROUP_CONCAT(field, ',') as discrepant_fields
FROM (SELECT trade_id, field FROM discrepancies ORDER BY trade_id, field)
GROUP BY trade_id;
"

# Import data, compute G-33 values, find discrepancies via Python helper
python3 /app/reconcile_helper.py "$DB"

# Export discrepancies to JSON using sqlite3 JSON output + Python type conversion
sqlite3 -json "$DB" \
    "SELECT trade_id, field, vendor_value, correct_value FROM discrepancies ORDER BY trade_id, field" | \
python3 -c "
import json, sys
rows = json.load(sys.stdin)
for r in rows:
    for k in ('vendor_value', 'correct_value'):
        v = r[k]
        if v is None:
            continue
        try:
            r[k] = float(v)
        except (ValueError, TypeError):
            pass
json.dump(rows, sys.stdout, indent=2)
" > /app/output/discrepancies.json
