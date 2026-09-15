#!/bin/bash

set -e
cd /app

# Step 1: Create database and import CSVs using sqlite3 CLI
rm -f billing.db

sqlite3 billing.db < schema.sql

for f in data/*.csv; do
    table=$(basename "$f" .csv)
    sqlite3 billing.db ".import --csv --skip 1 $f $table"
done

# Step 2: Create SQL views via sqlite3 CLI
sqlite3 billing.db "
CREATE VIEW IF NOT EXISTS v_billing_group_aggregate AS
SELECT
    bg.id AS group_id,
    bg.leader_id,
    COALESCE(SUM(rbv.payment_orders), 0) AS total_payment_orders,
    COUNT(bgm.participant_id) AS member_count
FROM billing_groups bg
JOIN billing_group_members bgm ON bg.id = bgm.group_id
LEFT JOIN rtgs_bank_volumes rbv ON bgm.participant_id = rbv.participant_id
GROUP BY bg.id, bg.leader_id;
"

# Step 3: Run Python billing computation
python3 /app/billing_engine.py

# Step 4: Export audit CSV via sqlite3 CLI
sqlite3 -header -csv billing.db \
    "SELECT * FROM fee_breakdown ORDER BY participant_id;" \
    > audit.csv
