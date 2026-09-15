#!/bin/bash
# Prepare ClickHouse directories with root ownership so the server
# can run as root without MISMATCHING_USERS_FOR_PROCESS_AND_DATA errors.
mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server
chown -R root:root /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server
rm -f /var/run/clickhouse-server/clickhouse-server.pid /run/clickhouse-server/clickhouse-server.pid 2>/dev/null

# Do NOT start ClickHouse here — the task requires the agent to manage
# the server lifecycle.  Starting it in the entrypoint caused port-conflict
# failures when solve.sh / test.sh also tried to start it.

exec "$@"
