#!/bin/bash

set -euo pipefail

# Install solution dependencies
pip3 install requests==2.32.3 -q

# -----------------------------------------------------------------------
# 0. Set up hostname resolution for cluster communication
# -----------------------------------------------------------------------
echo "127.0.0.1 node-primary" >> /etc/hosts
echo "127.0.0.1 node-secondary" >> /etc/hosts

# -----------------------------------------------------------------------
# 1. Start primary Weaviate instance on port 8080
#    RAFT defaults: RAFT_PORT=8300, RAFT_INTERNAL_RPC_PORT=8301
# -----------------------------------------------------------------------
echo "Starting primary Weaviate instance on port 8080..."

PERSISTENCE_DATA_PATH=/app/weaviate_data_primary \
CLUSTER_HOSTNAME=node-primary \
CLUSTER_ADVERTISE_ADDR=127.0.0.1 \
CLUSTER_GOSSIP_BIND_PORT=7946 \
CLUSTER_DATA_BIND_PORT=7947 \
RAFT_PORT=8300 \
RAFT_INTERNAL_RPC_PORT=8301 \
RAFT_BOOTSTRAP_EXPECT=1 \
RAFT_JOIN=node-primary:8300 \
AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
DEFAULT_VECTORIZER_MODULE=none \
QUERY_DEFAULTS_LIMIT=100 \
GRPC_PORT=50051 \
GO_PROFILING_PORT=6060 \
GOMEMLIMIT=512MiB \
nohup /usr/local/bin/weaviate --host 0.0.0.0 --port 8080 --scheme http \
  > /tmp/weaviate_primary.log 2>&1 &
PRIMARY_PID=$!
disown $PRIMARY_PID

echo "Primary PID: $PRIMARY_PID"

# Wait for primary to become ready
echo "Waiting for primary instance to be ready..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:8080/v1/.well-known/ready > /dev/null 2>&1; then
        echo "Primary instance ready."
        break
    fi
    if [ "$i" -eq 90 ]; then
        echo "ERROR: Primary instance did not become ready in time."
        cat /tmp/weaviate_primary.log
        exit 1
    fi
    sleep 2
done

# -----------------------------------------------------------------------
# 2. Create collections, add tenants, load data on primary
# -----------------------------------------------------------------------
echo "Setting up collections and loading data on primary..."
python3 /solution/setup_primary.py

# -----------------------------------------------------------------------
# 3. Start secondary Weaviate instance on port 8079
#    CRITICAL: All ports must differ from primary — HTTP, gRPC, gossip,
#    data, RAFT, RAFT internal RPC, and Go profiling.
# -----------------------------------------------------------------------
echo "Starting secondary Weaviate instance on port 8079..."

PERSISTENCE_DATA_PATH=/app/weaviate_data_restored \
CLUSTER_HOSTNAME=node-secondary \
CLUSTER_ADVERTISE_ADDR=127.0.0.1 \
CLUSTER_GOSSIP_BIND_PORT=7956 \
CLUSTER_DATA_BIND_PORT=7957 \
RAFT_PORT=8310 \
RAFT_INTERNAL_RPC_PORT=8311 \
RAFT_BOOTSTRAP_EXPECT=1 \
RAFT_JOIN=node-secondary:8310 \
AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
DEFAULT_VECTORIZER_MODULE=none \
QUERY_DEFAULTS_LIMIT=100 \
GRPC_PORT=50052 \
GO_PROFILING_PORT=6061 \
GOMEMLIMIT=512MiB \
nohup /usr/local/bin/weaviate --host 0.0.0.0 --port 8079 --scheme http \
  > /tmp/weaviate_secondary.log 2>&1 &
SECONDARY_PID=$!
disown $SECONDARY_PID

echo "Secondary PID: $SECONDARY_PID"

# Wait for secondary to become ready (longer timeout due to shared CPU)
echo "Waiting for secondary instance to be ready..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:8079/v1/.well-known/ready > /dev/null 2>&1; then
        echo "Secondary instance ready."
        break
    fi
    if [ "$i" -eq 90 ]; then
        echo "ERROR: Secondary instance did not become ready in time."
        cat /tmp/weaviate_secondary.log
        exit 1
    fi
    sleep 2
done

# -----------------------------------------------------------------------
# 4. Migrate all schema and data from primary to secondary
# -----------------------------------------------------------------------
echo "Migrating data from primary to secondary instance..."
python3 /solution/migrate_data.py

echo ""
echo "=== Task complete ==="
echo "Primary instance:   http://localhost:8080 (PID $PRIMARY_PID)"
echo "Secondary instance: http://localhost:8079 (PID $SECONDARY_PID)"
