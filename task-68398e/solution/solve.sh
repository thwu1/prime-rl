#!/bin/bash


set -e

pip3 install pyyaml==6.0.2 -q

# ============================================================
# 1. Fix PKI Certificates
# ============================================================
echo "=== Fixing PKI certificates ==="
mkdir -p /app/pki-fixed

# Copy valid CA files
cp /app/pki/ca.crt /app/pki-fixed/
cp /app/pki/ca.key /app/pki-fixed/
cp /app/pki/front-proxy-ca.crt /app/pki-fixed/
cp /app/pki/front-proxy-ca.key /app/pki-fixed/

# Fix 1: API server cert - regenerate with ALL required SANs
openssl genrsa -out /app/pki-fixed/apiserver.key 2048 2>/dev/null
cat > /tmp/apiserver-san-fixed.cnf << 'EOF'
[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name
[req_distinguished_name]
[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
[alt_names]
DNS.1 = kubernetes
DNS.2 = kubernetes.default
DNS.3 = kubernetes.default.svc
DNS.4 = kubernetes.default.svc.cluster.local
DNS.5 = localhost
IP.1 = 127.0.0.1
IP.2 = 10.96.0.1
IP.3 = 192.168.1.10
EOF
openssl req -new -key /app/pki-fixed/apiserver.key -out /tmp/apiserver-fixed.csr \
  -subj "/CN=kube-apiserver" -config /tmp/apiserver-san-fixed.cnf
openssl x509 -req -in /tmp/apiserver-fixed.csr \
  -CA /app/pki/ca.crt -CAkey /app/pki/ca.key -CAcreateserial \
  -out /app/pki-fixed/apiserver.crt -days 365 -sha256 \
  -extensions v3_req -extfile /tmp/apiserver-san-fixed.cnf 2>/dev/null
echo "  Fixed apiserver.crt with all required SANs"

# Fix 2: Admin cert - regenerate with correct Organization (system:masters)
openssl genrsa -out /app/pki-fixed/admin.key 2048 2>/dev/null
openssl req -new -key /app/pki-fixed/admin.key -out /tmp/admin-fixed.csr \
  -subj "/O=system:masters/CN=kubernetes-admin"
openssl x509 -req -in /tmp/admin-fixed.csr \
  -CA /app/pki/ca.crt -CAkey /app/pki/ca.key -CAcreateserial \
  -out /app/pki-fixed/admin.crt -days 365 -sha256 2>/dev/null
echo "  Fixed admin.crt with O=system:masters"

# Fix 3: Scheduler cert - regenerate signed by main CA (not front-proxy-ca)
openssl genrsa -out /app/pki-fixed/scheduler.key 2048 2>/dev/null
openssl req -new -key /app/pki-fixed/scheduler.key -out /tmp/scheduler-fixed.csr \
  -subj "/CN=system:kube-scheduler"
openssl x509 -req -in /tmp/scheduler-fixed.csr \
  -CA /app/pki/ca.crt -CAkey /app/pki/ca.key -CAcreateserial \
  -out /app/pki-fixed/scheduler.crt -days 365 -sha256 2>/dev/null
echo "  Fixed scheduler.crt signed by main CA"

# Clean up temp files
rm -f /tmp/apiserver-san-fixed.cnf /tmp/*.csr /tmp/*.srl

# ============================================================
# 2. Fix Static Pod Manifests
# ============================================================
echo "=== Fixing static pod manifests ==="
python3 /solution/fix_manifests.py

# ============================================================
# 3. etcd Backup/Restore
# ============================================================
echo "=== Performing etcd backup/restore ==="

# Restore snapshot to /app/etcd/restored/
etcdutl snapshot restore /app/etcd/pre-failure-snapshot.db \
  --data-dir /app/etcd/restored 2>/dev/null
echo "  Restored snapshot to /app/etcd/restored/"

# Start etcd from restored data
etcd --data-dir /app/etcd/restored \
  --listen-client-urls http://127.0.0.1:2379 \
  --advertise-client-urls http://127.0.0.1:2379 \
  --log-level error &
ETCD_PID=$!
sleep 3

# Verify data
export ETCDCTL_API=3
VALUE=$(etcdctl --endpoints=http://127.0.0.1:2379 get /cluster/config/name --print-value-only)
echo "  Verified /cluster/config/name = ${VALUE}"

# Create new backup
etcdctl --endpoints=http://127.0.0.1:2379 snapshot save /app/etcd/backup.db 2>/dev/null
echo "  Created backup at /app/etcd/backup.db"

# Stop etcd
kill $ETCD_PID
wait $ETCD_PID 2>/dev/null || true

# ============================================================
# 4. Fix Kubeconfig
# ============================================================
echo "=== Fixing kubeconfig ==="
python3 /solution/fix_kubeconfig.py

# ============================================================
# 5. Create RBAC Manifests
# ============================================================
echo "=== Creating RBAC manifests ==="
python3 /solution/create_rbac.py

echo "=== All fixes complete ==="
