#!/usr/bin/env bash
# CDS pricing pipeline: preprocess raw market data, compile, and run
set -e

cd /app

echo "=== Step 1: Preprocess market data ==="

# Decode base64-encoded yield curve
base64 -d data/yield_curve.b64 > data/yield_curve.csv

# Transform raw trade feed to pricer-compatible JSON format.
# The raw feed uses different field names and unit conventions
# than what the DataLoader expects.
jq '{
  valuation_date: .snapshot.val_date,
  stepin_date: .snapshot.step_in,
  recovery_rate: .market_data.recovery_pct,
  notional: .portfolio.notional,
  fixed_rate: .portfolio.coupon,
  model_conventions: .conventions,
  trades: [.portfolio.positions[] | {
    id: .id,
    buy_sell: .direction,
    start_date: .start,
    end_date: .end,
    frequency_months: .freq
  }]
}' data/trades_raw.json > data/trades.json

echo "=== Step 2: Build with Maven ==="
mvn -q compile

echo "=== Step 3: Run CDS Pricer ==="
mvn -q exec:java
