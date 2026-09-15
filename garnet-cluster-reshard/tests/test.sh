#!/bin/bash

pip3 install pytest==8.3.4 redis==5.2.1 -q

# Kill any existing garnet processes for a clean start
pkill -f garnet-server 2>/dev/null || true
sleep 2

# Verify garnet-server is on PATH
echo "=== Checking garnet-server availability ==="
which garnet-server || { echo "ERROR: garnet-server not found on PATH"; echo "PATH=$PATH"; mkdir -p /logs/verifier; echo "0.0" > /logs/verifier/reward.txt; exit 1; }

# Start the initial 3-node cluster
echo "=== Setting up initial cluster ==="
bash /opt/garnet/init_cluster.sh
INIT_EXIT=$?
if [ $INIT_EXIT -ne 0 ]; then
    echo "Failed to initialize cluster (exit code $INIT_EXIT)"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the agent's resharding solution
echo "=== Running resharding solution ==="
if [ ! -f /app/reshard.py ]; then
    echo "ERROR: /app/reshard.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

python3 /app/reshard.py
RESHARD_EXIT=$?
if [ $RESHARD_EXIT -ne 0 ]; then
    echo "Resharding script failed (exit code $RESHARD_EXIT)"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest verification
echo "=== Running verification tests ==="
python3 -m pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
