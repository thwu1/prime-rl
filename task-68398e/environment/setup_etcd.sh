#!/bin/bash
set -e

mkdir -p /app/etcd

# Start etcd with a temporary data directory
etcd --data-dir /tmp/etcd-build-data \
  --listen-client-urls http://127.0.0.1:2379 \
  --advertise-client-urls http://127.0.0.1:2379 \
  --log-level error &
ETCD_PID=$!
sleep 3

export ETCDCTL_API=3

# Write realistic cluster configuration data
etcdctl --endpoints=http://127.0.0.1:2379 put /cluster/config/name "production-cluster"
etcdctl --endpoints=http://127.0.0.1:2379 put /cluster/config/region "us-east-1"
etcdctl --endpoints=http://127.0.0.1:2379 put /cluster/config/environment "production"
etcdctl --endpoints=http://127.0.0.1:2379 put /cluster/config/k8s-version "v1.31.0"
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/namespaces/default '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"default"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/namespaces/kube-system '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"kube-system"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/namespaces/production '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"production"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/namespaces/ci-cd '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"ci-cd"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/services/default/kubernetes '{"apiVersion":"v1","kind":"Service","metadata":{"name":"kubernetes","namespace":"default"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/services/kube-system/kube-dns '{"apiVersion":"v1","kind":"Service","metadata":{"name":"kube-dns","namespace":"kube-system"}}'
etcdctl --endpoints=http://127.0.0.1:2379 put /registry/configmaps/kube-system/coredns '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"coredns","namespace":"kube-system"}}'

# Create snapshot
etcdctl --endpoints=http://127.0.0.1:2379 snapshot save /app/etcd/pre-failure-snapshot.db

# Stop etcd
kill $ETCD_PID
wait $ETCD_PID 2>/dev/null || true

# Clean up temporary data
rm -rf /tmp/etcd-build-data
