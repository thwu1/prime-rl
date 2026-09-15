#!/bin/bash

# Part 1: WAL recovery
cp /solution/wal_recovery.py /app/wal_recovery.py
python3 /app/wal_recovery.py /app/data/sensor_data.db

# Part 2: Litestream replication validation
cp /solution/litestream.yml /app/litestream.yml
cp /solution/validate_replication.sh /app/validate_replication.sh
bash /app/validate_replication.sh
