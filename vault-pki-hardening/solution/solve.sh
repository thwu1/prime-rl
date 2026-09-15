#!/bin/bash

set -e

export VAULT_ADDR='http://127.0.0.1:8200'

# Start Vault if not running
if ! vault status -format=json > /dev/null 2>&1; then
    vault server -config=/app/vault-config.hcl > /tmp/vault-solve.log 2>&1 &
    sleep 5
fi

# Unseal if sealed
SEALED=$(vault status -format=json 2>/dev/null | jq -r '.sealed' 2>/dev/null || echo "true")
if [ "$SEALED" = "true" ]; then
    vault operator unseal $(cat /app/vault-creds/unseal-key-1)
    vault operator unseal $(cat /app/vault-creds/unseal-key-2)
    sleep 2
fi

export VAULT_TOKEN=$(cat /app/vault-creds/root-token)

# =================================================================
# 1. Fix PKI Root CA — tune mount TTL and regenerate root certificate
# =================================================================
vault secrets tune -max-lease-ttl=87600h pki

vault write pki/root/generate/internal \
    common_name="Example Root CA" \
    ttl=87600h \
    key_bits=4096

vault write pki/config/urls \
    issuing_certificates="http://127.0.0.1:8200/v1/pki/ca" \
    crl_distribution_points="http://127.0.0.1:8200/v1/pki/crl"

# =================================================================
# 2. Fix Intermediate CA — re-sign with the new root
# =================================================================
vault write -format=json pki_int/intermediate/generate/internal \
    common_name="Example Intermediate CA" \
    key_bits=4096 \
    | jq -r '.data.csr' > /tmp/pki_int.csr

vault write -format=json pki/root/sign-intermediate \
    csr=@/tmp/pki_int.csr \
    format=pem_bundle \
    ttl=43800h \
    max_path_length=0 \
    | jq -r '.data.certificate' > /tmp/intermediate.cert.pem

vault write pki_int/intermediate/set-signed \
    certificate=@/tmp/intermediate.cert.pem

vault write pki_int/config/urls \
    issuing_certificates="http://127.0.0.1:8200/v1/pki_int/ca" \
    crl_distribution_points="http://127.0.0.1:8200/v1/pki_int/crl"

# =================================================================
# 3. Fix web-server role — restrict domains, increase key size
# =================================================================
vault write pki_int/roles/web-server \
    allowed_domains="example.com" \
    allow_subdomains=true \
    allow_any_name=false \
    max_ttl=720h \
    key_bits=4096 \
    require_cn=true

# =================================================================
# 4. Upgrade KV v1 to v2 (must happen before policy path changes)
# =================================================================
vault kv enable-versioning secret/
sleep 1

# =================================================================
# 5. Fix app-readonly policy (use KV v2 paths, read-only)
# =================================================================
vault policy write app-readonly - <<'POLICY'
path "secret/data/app/*" {
  capabilities = ["read", "list"]
}
path "secret/metadata/app/*" {
  capabilities = ["read", "list"]
}
POLICY

# =================================================================
# 6. Fix cert-issuer policy (scoped to web-server role only)
# =================================================================
vault policy write cert-issuer - <<'POLICY'
path "pki_int/issue/web-server" {
  capabilities = ["create", "update"]
}
path "pki_int/certs" {
  capabilities = ["list"]
}
path "pki/cert/ca" {
  capabilities = ["read"]
}
POLICY

# =================================================================
# 7. Fix AppRole — finite TTLs, CIDR restrictions, use limits
# =================================================================
vault write auth/approle/role/webapp \
    token_policies="app-readonly" \
    token_ttl=3600 \
    token_max_ttl=14400 \
    secret_id_bound_cidrs="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16" \
    token_num_uses=10

# =================================================================
# 8. Enable audit device
# =================================================================
mkdir -p /var/log/vault
vault audit enable file file_path=/var/log/vault/audit.log 2>/dev/null || true

# =================================================================
# 9. Issue leaf certificate for app.example.com
# =================================================================
mkdir -p /app/certs
CERT_OUTPUT=$(vault write -format=json pki_int/issue/web-server \
    common_name="app.example.com" \
    ttl=72h)

echo "$CERT_OUTPUT" | jq -r '.data.certificate' > /app/certs/app.example.com.crt
echo "$CERT_OUTPUT" | jq -r '.data.private_key' > /app/certs/app.example.com.key
echo "$CERT_OUTPUT" | jq -r '.data.ca_chain[]' > /app/certs/ca-chain.pem

# Clean up temp files
rm -f /tmp/pki_int.csr /tmp/intermediate.cert.pem

echo "All remediation steps complete."
