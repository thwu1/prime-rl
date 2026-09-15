#!/bin/bash
set -e

echo "=== Initializing 3-node Garnet cluster ==="

# Clean up any existing processes
pkill -f garnet-server 2>/dev/null || true
sleep 2

# Create data directories
for port in 7000 7001 7002; do
    rm -rf /tmp/garnet/$port
    mkdir -p /tmp/garnet/$port
done

# Start Garnet instances with explicit --cluster and --aof flags
for port in 7000 7001 7002; do
    garnet-server --port $port --checkpointdir /tmp/garnet/$port \
        --cluster --aof \
        --config-import-path /opt/garnet/garnet.conf \
        > /tmp/garnet/$port/server.log 2>&1 &
    echo "Started garnet-server on port $port (PID $!)"
done

# Wait for instances to be ready (60s timeout for slow environments)
for port in 7000 7001 7002; do
    echo -n "Waiting for port $port..."
    for i in $(seq 1 60); do
        if redis-cli -h 127.0.0.1 -p $port PING 2>/dev/null | grep -q PONG; then
            echo " ready"
            break
        fi
        sleep 1
        if [ $i -eq 60 ]; then
            echo " TIMEOUT"
            echo "--- Server log for port $port ---"
            cat /tmp/garnet/$port/server.log
            echo "--- End log ---"
            exit 1
        fi
    done
done

# Set config epochs (must be done while nodes table is empty)
redis-cli -h 127.0.0.1 -p 7000 CLUSTER SET-CONFIG-EPOCH 1
redis-cli -h 127.0.0.1 -p 7001 CLUSTER SET-CONFIG-EPOCH 2
redis-cli -h 127.0.0.1 -p 7002 CLUSTER SET-CONFIG-EPOCH 3

# Assign slot ranges
redis-cli -h 127.0.0.1 -p 7000 CLUSTER ADDSLOTSRANGE 0 5460
redis-cli -h 127.0.0.1 -p 7001 CLUSTER ADDSLOTSRANGE 5461 10922
redis-cli -h 127.0.0.1 -p 7002 CLUSTER ADDSLOTSRANGE 10923 16383

# Introduce nodes to each other via gossip
redis-cli -h 127.0.0.1 -p 7000 CLUSTER MEET 127.0.0.1 7001
redis-cli -h 127.0.0.1 -p 7000 CLUSTER MEET 127.0.0.1 7002

# Wait for gossip propagation
echo "Waiting for gossip propagation..."
sleep 8

# Verify cluster formation
echo "Cluster topology:"
redis-cli -h 127.0.0.1 -p 7000 CLUSTER NODES

# Seed 500 keys using the fast Python loader
echo "Loading 500 keys..."
python3 /opt/garnet/seed_keys.py

echo "=== Cluster initialization complete ==="
