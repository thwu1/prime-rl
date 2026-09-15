#!/bin/bash

set -e
cd /app

DB_PATH="/app/regsho.db"
rm -f "$DB_PATH"

# Create table schemas
sqlite3 "$DB_PATH" <<'SCHEMA'
CREATE TABLE short_interest (
    accountingYearMonthNumber TEXT,
    symbolCode TEXT,
    issueName TEXT,
    issuerServicesGroupExchangeCode TEXT,
    marketClassCode TEXT,
    currentShortPositionQuantity INTEGER,
    previousShortPositionQuantity INTEGER,
    stockSplitFlag TEXT,
    averageDailyVolumeQuantity INTEGER,
    daysToCoverQuantity REAL,
    revisionFlag TEXT,
    changePercent REAL,
    changePreviousNumber INTEGER,
    settlementDate TEXT
);

CREATE TABLE venue_volume (
    Date TEXT,
    Symbol TEXT,
    ShortVolume REAL,
    ShortExemptVolume REAL,
    TotalVolume REAL,
    Market TEXT,
    venue TEXT
);

CREATE TABLE threshold_list (
    tradeDate TEXT,
    issueSymbolIdentifier TEXT,
    issueName TEXT,
    marketClassCode TEXT,
    thresholdListFlag TEXT,
    marketCategoryDescription TEXT,
    regShoThresholdFlag TEXT,
    rule4320Flag TEXT
);
SCHEMA

# Import consolidated short interest CSV via sqlite3 .import
sqlite3 "$DB_PATH" <<'IMPORT_SI'
.import --csv --skip 1 /app/data/consolidated_si.csv short_interest
IMPORT_SI

# Preprocess venue files with awk: strip header, filter data rows (NF==6),
# append venue tag derived from filename prefix before "_volume"
awk -F'|' 'NR>1 && NF==6 {print $0"|FNSQ"}' /app/data/fnsq_volume.txt > /tmp/venue_combined.txt
awk -F'|' 'NR>1 && NF==6 {print $0"|FNYX"}' /app/data/fnyx_volume.txt >> /tmp/venue_combined.txt

# Import preprocessed venue data
sqlite3 "$DB_PATH" <<'IMPORT_VENUE'
.separator "|"
.import /tmp/venue_combined.txt venue_volume
IMPORT_VENUE

# Import threshold list CSV via sqlite3 .import
sqlite3 "$DB_PATH" <<'IMPORT_TH'
.import --csv --skip 1 /app/data/threshold_list.csv threshold_list
IMPORT_TH

# Create analytical views
sqlite3 "$DB_PATH" <<'VIEWS'
CREATE VIEW venue_symbol_agg AS
WITH raw_agg AS (
    SELECT
        Symbol AS symbol,
        CAST(SUM(ShortVolume) AS INTEGER) AS short_volume,
        CAST(SUM(ShortExemptVolume) AS INTEGER) AS short_exempt_volume,
        CAST(SUM(TotalVolume) AS INTEGER) AS total_volume,
        COUNT(DISTINCT venue) AS venue_count
    FROM venue_volume
    GROUP BY Symbol
)
SELECT
    symbol,
    short_volume,
    short_exempt_volume,
    total_volume,
    CASE
        WHEN total_volume > 0 THEN ROUND(1.0 * short_volume / total_volume, 6)
        ELSE 0.0
    END AS short_ratio,
    venue_count
FROM raw_agg;

CREATE VIEW threshold_streaks AS
WITH distinct_dates AS (
    SELECT DISTINCT tradeDate FROM threshold_list
),
dates_numbered AS (
    SELECT tradeDate,
           ROW_NUMBER() OVER (ORDER BY tradeDate) - 1 AS date_idx
    FROM distinct_dates
),
symbol_dates AS (
    SELECT DISTINCT t.issueSymbolIdentifier AS symbol,
           d.date_idx
    FROM threshold_list t
    JOIN dates_numbered d ON t.tradeDate = d.tradeDate
    WHERE t.regShoThresholdFlag = 'Y'
),
groups AS (
    SELECT symbol, date_idx,
           date_idx - ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date_idx) AS grp
    FROM symbol_dates
),
streaks AS (
    SELECT symbol, grp, COUNT(*) AS streak_len
    FROM groups
    GROUP BY symbol, grp
)
SELECT symbol,
       MAX(streak_len) AS max_consecutive_days,
       CASE WHEN MAX(streak_len) >= 5 THEN 1 ELSE 0 END AS closeout_eligible
FROM streaks
GROUP BY symbol;
VIEWS

echo "Database loaded:"
sqlite3 "$DB_PATH" "SELECT 'short_interest: ' || COUNT(*) FROM short_interest;"
sqlite3 "$DB_PATH" "SELECT 'venue_volume: ' || COUNT(*) FROM venue_volume;"
sqlite3 "$DB_PATH" "SELECT 'threshold_list: ' || COUNT(*) FROM threshold_list;"

# Run auditor reports
mkdir -p /app/output
python3 /app/regsho_auditor.py verify-si /app/data/consolidated_si.csv
python3 /app/regsho_auditor.py reconcile-venues /app/data/fnsq_volume.txt /app/data/fnyx_volume.txt
python3 /app/regsho_auditor.py threshold-monitor /app/data/threshold_list.csv

# Generate pipeline summary via jq
jq -n \
  --slurpfile si /app/output/si_verification.json \
  --slurpfile venue /app/output/venue_reconciliation.json \
  --slurpfile thresh /app/output/threshold_report.json \
  '{
    si_pass_rate: ($si[0].pass_count / $si[0].total_records),
    si_total: $si[0].total_records,
    venue_total_symbols: $venue[0].total_symbols,
    venue_multi_pct: (($venue[0].multi_venue_count / $venue[0].total_symbols) * 100),
    threshold_securities: $thresh[0].securities_tracked,
    threshold_closeout_count: ($thresh[0].closeout_triggered | length),
    closeout_symbols: [$thresh[0].closeout_triggered[].symbol]
  }' > /app/output/pipeline_summary.json

echo "Pipeline complete."
