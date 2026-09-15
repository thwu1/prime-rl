#!/usr/bin/env bash

cd /app

# Step 1: Run the linearizability checker
python3 /solution/checker.py

# Step 2: Start etcd for ground-truth verification
etcd --data-dir /app/etcd-data \
    --listen-client-urls http://127.0.0.1:2379 \
    --advertise-client-urls http://127.0.0.1:2379 \
    --listen-peer-urls http://127.0.0.1:2380 \
    --log-level warn &
ETCD_PID=$!
sleep 3

# Step 3: Replay ground-truth states and verify via etcdctl
python3 /solution/replay.py

# Step 4: Take snapshot with etcdctl and inspect with etcdutl
etcdctl --endpoints=http://127.0.0.1:2379 snapshot save /app/etcd-snapshot.db
etcdutl snapshot status /app/etcd-snapshot.db --write-out=table

# Cleanup
kill $ETCD_PID 2>/dev/null
wait $ETCD_PID 2>/dev/null
