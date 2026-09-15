#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Ensure ClickHouse directories and permissions
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server 2>/dev/null || true

# Start ClickHouse if not running
if ! clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
    rm -f /run/clickhouse-server/clickhouse-server.pid
    rm -f /var/lib/clickhouse/status
    clickhouse-server --daemon 2>/dev/null || clickhouse-server &
    sleep 5
    for i in $(seq 1 30); do
        clickhouse-client --query "SELECT 1" 2>/dev/null && break
        sleep 1
    done
fi

# Optimize all optimized tables for accurate measurement
for tbl in $(clickhouse-client --query "SELECT name FROM system.tables WHERE database='default' AND name LIKE 'optimized_%'" 2>/dev/null); do
    clickhouse-client --query "OPTIMIZE TABLE $tbl FINAL" 2>/dev/null || true
done

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
