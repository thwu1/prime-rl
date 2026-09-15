#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# --- Scenario 1: Use the dataset generated during build ---
mkdir -p /tmp/ref1/data /tmp/ref1/out
cp /app/data/accounts.dat /tmp/ref1/data/
cp /app/data/txns.dat /tmp/ref1/data/
cd /tmp/ref1 && /app/cobol/mainbatch

mkdir -p /tmp/mig1/data /tmp/mig1/out
cp /app/data/accounts.dat /tmp/mig1/data/
cp /app/data/txns.dat /tmp/mig1/data/
cd /tmp/mig1 && python3 /app/migrate/batch_post.py

# --- Scenario 2: Generate rounding/boundary edge case dataset ---
mkdir -p /tmp/gendata2
cd /tmp/gendata2 && SCENARIO=2 /app/cobol/gendata

mkdir -p /tmp/ref2/data /tmp/ref2/out
cp /tmp/gendata2/accounts.dat /tmp/ref2/data/
cp /tmp/gendata2/txns.dat /tmp/ref2/data/
cd /tmp/ref2 && /app/cobol/mainbatch

mkdir -p /tmp/mig2/data /tmp/mig2/out
cp /tmp/gendata2/accounts.dat /tmp/mig2/data/
cp /tmp/gendata2/txns.dat /tmp/mig2/data/
cd /tmp/mig2 && python3 /app/migrate/batch_post.py

# --- Scenario 3: Rate tier boundary probing dataset ---
mkdir -p /tmp/gendata3
cd /tmp/gendata3 && SCENARIO=3 /app/cobol/gendata

mkdir -p /tmp/ref3/data /tmp/ref3/out
cp /tmp/gendata3/accounts.dat /tmp/ref3/data/
cp /tmp/gendata3/txns.dat /tmp/ref3/data/
cd /tmp/ref3 && /app/cobol/mainbatch

mkdir -p /tmp/mig3/data /tmp/mig3/out
cp /tmp/gendata3/accounts.dat /tmp/mig3/data/
cp /tmp/gendata3/txns.dat /tmp/mig3/data/
cd /tmp/mig3 && python3 /app/migrate/batch_post.py

# Run pytest
cd /app
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
