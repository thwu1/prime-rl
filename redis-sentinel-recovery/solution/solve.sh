#!/bin/bash

pip3 install redis==5.0.1 -q

###############################################################################
# Step 0: Ensure supervisord is ready
###############################################################################
echo "=== Step 0: Waiting for supervisord ==="
mkdir -p /var/run /var/log/supervisor /var/log/redis
for i in $(seq 1 15); do
    if supervisorctl status >/dev/null 2>&1; then
        echo "supervisord is ready"
        break
    fi
    if [ "$i" -eq 15 ]; then
        supervisord -c /etc/supervisor/supervisord.conf
        sleep 3
    fi
    sleep 1
done

echo "Service status:"
supervisorctl status

###############################################################################
# Step 1: Stop Node A and fix AOF corruption
###############################################################################
echo "=== Step 1: Stopping Node A and fixing AOF ==="

# Node A is in FATAL state (AOF corruption, startretries=0).
# Stop it explicitly to ensure clean state for restart.
supervisorctl stop redis-node-a 2>/dev/null || true
sleep 1

# Show the error from the log
echo "Node A log (last 5 lines):"
tail -5 /var/log/redis/node-a.log 2>/dev/null || echo "(log not available)"

# Fix the corrupted AOF using redis-check-aof on the manifest file.
# Redis 7 multi-part AOF: manifest references base.rdb + incremental .aof files.
# The incr AOF has a truncated write at the end; --fix truncates the corrupt tail.
yes | redis-check-aof --fix /data/redis-node-a/appendonlydir/appendonly.aof.manifest

###############################################################################
# Step 2: Start Node A and verify it's operational
###############################################################################
echo "=== Step 2: Starting Node A ==="
supervisorctl start redis-node-a

# Wait for Node A to accept connections
for i in $(seq 1 30); do
    if redis-cli -p 6379 -a secretpass PING 2>/dev/null | grep -q PONG; then
        echo "Node A is responding to PING"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Node A failed to start after 30 seconds"
        tail -20 /var/log/redis/node-a.log 2>/dev/null
        exit 1
    fi
    sleep 1
done

echo "Node A DBSIZE:"
redis-cli -p 6379 -a secretpass DBSIZE

# Verify Node B is also running
echo "Node B PING:"
redis-cli -p 6380 -a secretpass PING

###############################################################################
# Step 3: Reconcile split-brain data (with financial safety override)
###############################################################################
echo "=== Step 3: Reconciling split-brain data ==="
python3 /solution/reconcile.py

echo "Post-reconciliation Node A DBSIZE:"
redis-cli -p 6379 -a secretpass DBSIZE

###############################################################################
# Step 4: Configure Node B as replica of Node A
###############################################################################
echo "=== Step 4: Setting up replication ==="
# Set masterauth before REPLICAOF (Node B must auth to Node A)
redis-cli -p 6380 -a secretpass CONFIG SET masterauth secretpass
redis-cli -p 6380 -a secretpass REPLICAOF 127.0.0.1 6379

# Wait for replication link to come up
for i in $(seq 1 30); do
    link_status=$(redis-cli -p 6380 -a secretpass INFO replication 2>/dev/null | grep master_link_status | tr -d '\r\n')
    if echo "$link_status" | grep -q "up"; then
        echo "Replication link is UP"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "WARNING: Replication link not up after 30s"
    fi
    sleep 1
done

redis-cli -p 6380 -a secretpass INFO replication 2>/dev/null | grep -E "role|master_link_status|connected_slaves"

###############################################################################
# Step 5: Fix Sentinel configurations (clean stale split-brain state)
###############################################################################
echo "=== Step 5: Fixing sentinels ==="
supervisorctl stop sentinel1 sentinel2 sentinel3
sleep 1

# Write clean sentinel configs from scratch.
# Sentinels rewrite configs at runtime with stale discovery state from the
# split-brain (wrong myid, epochs, known-replica, known-sentinel entries).
# Writing fresh configs is more reliable than sed cleanup.

cat > /etc/redis/sentinel1.conf << 'SEOF'
port 26379
daemonize no
logfile /var/log/redis/sentinel1.log
sentinel monitor mymaster 127.0.0.1 6379 2
sentinel auth-pass mymaster secretpass
sentinel down-after-milliseconds mymaster 600000
sentinel failover-timeout mymaster 600000
SEOF

cat > /etc/redis/sentinel2.conf << 'SEOF'
port 26380
daemonize no
logfile /var/log/redis/sentinel2.log
sentinel monitor mymaster 127.0.0.1 6379 2
sentinel auth-pass mymaster secretpass
sentinel down-after-milliseconds mymaster 600000
sentinel failover-timeout mymaster 600000
SEOF

cat > /etc/redis/sentinel3.conf << 'SEOF'
port 26381
daemonize no
logfile /var/log/redis/sentinel3.log
sentinel monitor mymaster 127.0.0.1 6379 2
sentinel auth-pass mymaster secretpass
sentinel down-after-milliseconds mymaster 600000
sentinel failover-timeout mymaster 600000
SEOF

supervisorctl start sentinel1 sentinel2 sentinel3
sleep 5

echo "Sentinel check:"
for port in 26379 26380 26381; do
    master_port=$(redis-cli -p $port SENTINEL MASTER mymaster 2>/dev/null | grep -A1 "^port$" | tail -1)
    echo "  Sentinel $port sees master on port: $master_port"
done

###############################################################################
# Step 6: Fix Flask application configuration
###############################################################################
echo "=== Step 6: Fixing Flask app ==="
sed -i "s/SENTINEL_SERVICE = 'redis-primary'/SENTINEL_SERVICE = 'mymaster'/" /app/app.py
sed -i "s/REDIS_PASSWORD = 'wrongpass'/REDIS_PASSWORD = 'secretpass'/" /app/app.py
supervisorctl restart flask-app
sleep 2

# Wait for Flask app to be ready
for i in $(seq 1 15); do
    if curl -s http://localhost:5000/health 2>/dev/null | grep -q '"ok"'; then
        echo "Flask app is healthy"
        break
    fi
    sleep 1
done

###############################################################################
# Final Verification
###############################################################################
echo "=== Final Verification ==="
echo "Master DBSIZE:"
redis-cli -p 6379 -a secretpass DBSIZE
echo "Replica DBSIZE:"
redis-cli -p 6380 -a secretpass DBSIZE
echo "App health:"
curl -s http://localhost:5000/health
echo ""
echo "App record count:"
curl -s http://localhost:5000/records/count
echo ""
echo "=== Recovery complete ==="
