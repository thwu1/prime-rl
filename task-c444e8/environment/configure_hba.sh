#!/bin/bash
set -e
PG_VERSION=$(ls /etc/postgresql/ | head -1)
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"
echo "local   all   all                  trust" > "$PG_HBA"
echo "host    all   all   127.0.0.1/32   trust" >> "$PG_HBA"
echo "host    all   all   ::1/128        trust" >> "$PG_HBA"
