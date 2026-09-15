#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

# Compile C library if not already compiled
if [ ! -f /app/lib/libcpamm.so ]; then
    cd /app/lib && make
fi

# Create SQLite database from SQL dump if not present
if [ ! -f /app/data/twamm.db ]; then
    sqlite3 /app/data/twamm.db < /app/data/init.sql
fi

cd /app
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
