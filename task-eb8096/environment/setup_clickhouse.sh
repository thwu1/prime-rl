#!/bin/bash
set -e

echo "Setting up ClickHouse..."

# Ensure directories and permissions
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server

# Start ClickHouse in background
clickhouse-server &
CH_PID=$!
sleep 5

# Wait for readiness
echo "Waiting for ClickHouse to start..."
for i in $(seq 1 60); do
    if clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
        echo "ClickHouse is ready"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: ClickHouse failed to start"
        exit 1
    fi
    sleep 1
done

# Create raw_logs table
echo "Creating raw_logs table..."
clickhouse-client --query "CREATE TABLE IF NOT EXISTS raw_logs (Body String, ServiceName LowCardinality(String)) ENGINE = MergeTree() ORDER BY tuple()"

# Load data
echo "Loading data..."
clickhouse-client --query "INSERT INTO raw_logs FORMAT TabSeparated" < /app/data/raw_logs.tsv

# Optimize to merge parts
echo "Optimizing table..."
clickhouse-client --query "OPTIMIZE TABLE raw_logs FINAL"

# Verify
echo "Verification:"
clickhouse-client --query "SELECT ServiceName, count() FROM raw_logs GROUP BY ServiceName ORDER BY ServiceName FORMAT TSV"
clickhouse-client --query "SELECT formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed, formatReadableSize(sum(data_compressed_bytes)) AS compressed FROM system.parts WHERE table='raw_logs' AND active FORMAT TSV"

# Stop ClickHouse
echo "Stopping ClickHouse..."
kill $CH_PID 2>/dev/null || true
wait $CH_PID 2>/dev/null || true
sleep 2

# Clean up for fresh restart
rm -f /run/clickhouse-server/clickhouse-server.pid
rm -f /var/lib/clickhouse/status

echo "Setup complete"
