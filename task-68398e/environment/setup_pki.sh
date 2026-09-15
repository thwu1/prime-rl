#!/bin/bash
set -e

PKI_DIR="/app/pki"

# --- Root CA (valid) ---
openssl genrsa -out ${PKI_DIR}/ca.key 2048 2>/dev/null
openssl req -x509 -new -nodes -key ${PKI_DIR}/ca.key -sha256 -days 3650 \
  -out ${PKI_DIR}/ca.crt -subj "/CN=kubernetes-ca/O=kubernetes"

# --- Front-Proxy CA (valid, used to trick scheduler cert) ---
openssl genrsa -out ${PKI_DIR}/front-proxy-ca.key 2048 2>/dev/null
openssl req -x509 -new -nodes -key ${PKI_DIR}/front-proxy-ca.key -sha256 -days 3650 \
  -out ${PKI_DIR}/front-proxy-ca.crt -subj "/CN=front-proxy-ca"

# --- ISSUE 1: API server cert with INCOMPLETE SANs ---
# Missing: kubernetes.default.svc, kubernetes.default.svc.cluster.local, 10.96.0.1, 192.168.1.10
openssl genrsa -out ${PKI_DIR}/apiserver.key 2048 2>/dev/null
cat > /tmp/apiserver-san.cnf << 'SANEOF'
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
DNS.3 = localhost
IP.1 = 127.0.0.1
SANEOF
openssl req -new -key ${PKI_DIR}/apiserver.key -out /tmp/apiserver.csr \
  -subj "/CN=kube-apiserver" -config /tmp/apiserver-san.cnf
openssl x509 -req -in /tmp/apiserver.csr -CA ${PKI_DIR}/ca.crt -CAkey ${PKI_DIR}/ca.key \
  -CAcreateserial -out ${PKI_DIR}/apiserver.crt -days 365 -sha256 \
  -extensions v3_req -extfile /tmp/apiserver-san.cnf 2>/dev/null

# --- ISSUE 2: Admin cert with wrong Organization ---
# O=system:admin (should be system:masters)
openssl genrsa -out ${PKI_DIR}/admin.key 2048 2>/dev/null
openssl req -new -key ${PKI_DIR}/admin.key -out /tmp/admin.csr \
  -subj "/O=system:admin/CN=kubernetes-admin"
openssl x509 -req -in /tmp/admin.csr -CA ${PKI_DIR}/ca.crt -CAkey ${PKI_DIR}/ca.key \
  -CAcreateserial -out ${PKI_DIR}/admin.crt -days 365 -sha256 2>/dev/null

# --- ISSUE 3: Scheduler cert signed by WRONG CA (front-proxy-ca instead of ca) ---
openssl genrsa -out ${PKI_DIR}/scheduler.key 2048 2>/dev/null
openssl req -new -key ${PKI_DIR}/scheduler.key -out /tmp/scheduler.csr \
  -subj "/CN=system:kube-scheduler"
openssl x509 -req -in /tmp/scheduler.csr \
  -CA ${PKI_DIR}/front-proxy-ca.crt -CAkey ${PKI_DIR}/front-proxy-ca.key \
  -CAcreateserial -out ${PKI_DIR}/scheduler.crt -days 365 -sha256 2>/dev/null

# --- Valid: Controller manager cert (reference) ---
openssl genrsa -out ${PKI_DIR}/controller-manager.key 2048 2>/dev/null
openssl req -new -key ${PKI_DIR}/controller-manager.key -out /tmp/cm.csr \
  -subj "/CN=system:kube-controller-manager"
openssl x509 -req -in /tmp/cm.csr -CA ${PKI_DIR}/ca.crt -CAkey ${PKI_DIR}/ca.key \
  -CAcreateserial -out ${PKI_DIR}/controller-manager.crt -days 365 -sha256 2>/dev/null

# --- Valid: etcd server cert ---
openssl genrsa -out ${PKI_DIR}/etcd-server.key 2048 2>/dev/null
cat > /tmp/etcd-san.cnf << 'ETCDSANEOF'
[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name
[req_distinguished_name]
[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = 192.168.1.10
ETCDSANEOF
openssl req -new -key ${PKI_DIR}/etcd-server.key -out /tmp/etcd.csr \
  -subj "/CN=etcd-server" -config /tmp/etcd-san.cnf
openssl x509 -req -in /tmp/etcd.csr -CA ${PKI_DIR}/ca.crt -CAkey ${PKI_DIR}/ca.key \
  -CAcreateserial -out ${PKI_DIR}/etcd-server.crt -days 365 -sha256 \
  -extensions v3_req -extfile /tmp/etcd-san.cnf 2>/dev/null

# --- Create broken kubeconfig ---
CA_DATA=$(cat ${PKI_DIR}/ca.crt | base64 -w 0)
ADMIN_CERT_DATA=$(cat ${PKI_DIR}/admin.crt | base64 -w 0)
ADMIN_KEY_DATA=$(cat ${PKI_DIR}/admin.key | base64 -w 0)

cat > /app/kubeconfig/admin.kubeconfig.broken << KCEOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA_DATA}
    server: https://localhost:8443
  name: kubernetes
contexts:
- context:
    cluster: kubernetes
    user: kubernetes-admin
  name: kubernetes-admin@kubernetes
current-context: kubernetes-admin@kubernetes
preferences: {}
users:
- name: kubernetes-admin
  user:
    client-certificate-data: ${ADMIN_CERT_DATA}
    client-key-data: ${ADMIN_KEY_DATA}
KCEOF

# Clean up temp files
rm -f /tmp/apiserver-san.cnf /tmp/etcd-san.cnf /tmp/*.csr /tmp/*.srl
