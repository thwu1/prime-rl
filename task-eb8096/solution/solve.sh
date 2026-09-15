#!/bin/bash

set -e

# Ensure ClickHouse directories and permissions
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server /run/clickhouse-server 2>/dev/null || true

# Start ClickHouse
rm -f /run/clickhouse-server/clickhouse-server.pid /var/lib/clickhouse/status
clickhouse-server --daemon 2>/dev/null || clickhouse-server &
sleep 5
for i in $(seq 1 30); do
    clickhouse-client --query "SELECT 1" 2>/dev/null && break
    sleep 1
done

# Run optimization
python3 /solution/optimize.py
