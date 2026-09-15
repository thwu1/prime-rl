#!/bin/bash

# Restore original sources if needed
if [ ! -f /app/engine.py ]; then
    cp /opt/app-src/*.py /app/
fi

# Fix engine bugs and implement missing features
python3 /solution/solve.py

# Build surveillance pipeline
mkdir -p /app/surveillance

# Extract orders from production log using jq
jq -r 'select(.type=="NEW_ORDER") | [.order_id, .trader_id, .side, .price, .quantity, .timestamp] | @csv' \
    /app/production.jsonl > /tmp/orders.csv

# Extract trades using jq
jq -r 'select(.type=="TRADE") | [.trade_id, .buy_order_id, .sell_order_id, .buyer_id, .seller_id, .price, .quantity, .timestamp] | @csv' \
    /app/production.jsonl > /tmp/trades.csv

# Extract cancellations using jq
jq -r 'select(.type=="CANCEL") | [.target_order_id, .timestamp] | @csv' \
    /app/production.jsonl > /tmp/cancels.csv

# Create SQLite database schema and import data
sqlite3 /app/surveillance/exchange.db "CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    trader_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    timestamp INTEGER NOT NULL
);"

sqlite3 /app/surveillance/exchange.db "CREATE TABLE trades (
    trade_id INTEGER PRIMARY KEY,
    buy_order_id INTEGER NOT NULL,
    sell_order_id INTEGER NOT NULL,
    buyer_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    price TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    timestamp INTEGER NOT NULL
);"

sqlite3 /app/surveillance/exchange.db "CREATE TABLE cancellations (
    target_order_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL
);"

sqlite3 -csv /app/surveillance/exchange.db ".import /tmp/orders.csv orders"
sqlite3 -csv /app/surveillance/exchange.db ".import /tmp/trades.csv trades"
sqlite3 -csv /app/surveillance/exchange.db ".import /tmp/cancels.csv cancellations"

# Wash pairs: trader pairs with >= 4 mutual trades
sqlite3 -header -csv /app/surveillance/exchange.db \
    "SELECT buyer_id, seller_id, COUNT(*) as trade_count
     FROM trades
     GROUP BY buyer_id, seller_id
     HAVING COUNT(*) >= 4
     ORDER BY trade_count DESC;" > /app/surveillance/wash_pairs.csv

# Cancel ratios: per-trader cancel ratio
sqlite3 -header -csv /app/surveillance/exchange.db \
    "SELECT
        o.trader_id,
        COUNT(DISTINCT o.order_id) as orders,
        COUNT(DISTINCT c.target_order_id) as cancels,
        ROUND(CAST(COUNT(DISTINCT c.target_order_id) AS REAL) / COUNT(DISTINCT o.order_id), 4) as ratio
     FROM orders o
     LEFT JOIN cancellations c ON o.order_id = c.target_order_id
     GROUP BY o.trader_id
     ORDER BY ratio DESC, o.trader_id ASC;" > /app/surveillance/cancel_ratios.csv

# VWAP: volume-weighted average price
sqlite3 /app/surveillance/exchange.db \
    "SELECT ROUND(SUM(CAST(price AS REAL) * quantity) / SUM(quantity), 4)
     FROM trades;" > /app/surveillance/vwap.txt
