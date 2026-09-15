#!/bin/bash


# Start PostgreSQL if not already running
if ! pg_isready -q 2>/dev/null; then
    PG_VER=$(ls /etc/postgresql/ | head -1)
    pg_ctlcluster $PG_VER main start
    for i in $(seq 1 30); do
        if pg_isready -q 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi

# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
