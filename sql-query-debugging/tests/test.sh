#!/bin/bash

# Start PostgreSQL
PG_VER=$(pg_lsclusters -h | awk '{print $1}')
pg_ctlcluster "$PG_VER" main start
sleep 2
pg_isready || { echo "PostgreSQL failed to start"; exit 1; }

pip3 install pytest==8.3.4 psycopg2-binary==2.9.9 -q

python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
