#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not running
pg_isready -U postgres -q 2>/dev/null || {
    PG_VER=$(ls /etc/postgresql/ | head -1)
    pg_ctlcluster "$PG_VER" main start
}
until pg_isready -U postgres -q; do sleep 0.5; done

# Ensure statistics are current
psql -U postgres -d eventdb -c "ANALYZE app.events;" 2>/dev/null

# Run tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
