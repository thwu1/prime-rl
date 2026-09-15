#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# ------------------------------------------------------------------
# Robust ClickHouse startup — kill any zombie, start fresh as root
# ------------------------------------------------------------------
if ! clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
    # Kill any lingering ClickHouse process so ports are freed
    pkill -9 -f clickhouse-server 2>/dev/null || true
    sleep 2

    mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server
    chown -R root:root /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server
    rm -f /var/run/clickhouse-server/clickhouse-server.pid /run/clickhouse-server/clickhouse-server.pid 2>/dev/null

    clickhouse-server --config-file=/etc/clickhouse-server/config.xml --daemon 2>/dev/null || true

    for i in $(seq 1 120); do
        clickhouse-client --query "SELECT 1" >/dev/null 2>&1 && break
        sleep 1
    done
fi

# Run pytest and capture exit code
pytest /tests/test_state.py -v
RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
