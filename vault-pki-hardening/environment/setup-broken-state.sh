#!/bin/bash
set -e

export VAULT_ADDR='http://127.0.0.1:8200'

# Start Vault server
vault server -config=/app/vault-config.hcl > /tmp/vault.log 2>&1 &
VAULT_PID=$!
sleep 5

# Initialize Vault with 3 key shares, threshold 2
INIT_OUTPUT=$(vault operator init -key-shares=3 -key-threshold=2 -format=json)
echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[0]' > /app/vault-creds/unseal-key-1
echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[1]' > /app/vault-creds/unseal-key-2
echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[2]' > /app/vault-creds/unseal-key-3
echo "$INIT_OUTPUT" | jq -r '.root_token' > /app/vault-creds/root-token

# Unseal
vault operator unseal $(cat /app/vault-creds/unseal-key-1)
vault operator unseal $(cat /app/vault-creds/unseal-key-2)

export VAULT_TOKEN=$(cat /app/vault-creds/root-token)

# === BROKEN STATE: PKI Root CA with 30-day TTL (should be 10+ years) ===
vault secrets enable -path=pki -max-lease-ttl=720h pki
vault write pki/root/generate/internal \
    common_name="Example Root CA" \
    ttl=720h

# === BROKEN STATE: PKI Intermediate CA signed with short-lived root ===
vault secrets enable -path=pki_int -max-lease-ttl=43800h pki

vault write -format=json pki_int/intermediate/generate/internal \
    common_name="Example Intermediate CA" \
    | jq -r '.data.csr' > /tmp/pki_int.csr

vault write -format=json pki/root/sign-intermediate \
    csr=@/tmp/pki_int.csr \
    format=pem_bundle \
    ttl=720h \
    | jq -r '.data.certificate' > /tmp/intermediate.cert.pem

vault write pki_int/intermediate/set-signed \
    certificate=@/tmp/intermediate.cert.pem

# === BROKEN STATE: Overly permissive certificate role ===
vault write pki_int/roles/web-server \
    allow_any_name=true \
    allow_subdomains=true \
    max_ttl=8760h \
    key_bits=2048

# === BROKEN STATE: Overly permissive policies ===
vault policy write app-readonly - <<'POLICY1'
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}
path "pki_int/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
POLICY1

vault policy write cert-issuer - <<'POLICY2'
path "pki_int/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "pki/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
POLICY2

# === BROKEN STATE: Insecure AppRole configuration ===
vault auth enable approle
vault write auth/approle/role/webapp \
    token_policies="app-readonly" \
    token_ttl=0 \
    token_max_ttl=0 \
    secret_id_num_uses=0 \
    token_num_uses=0

# === BROKEN STATE: KV v1 instead of v2, no audit ===
vault secrets disable secret/
vault secrets enable -path=secret -version=1 kv
vault kv put secret/app/database username="dbuser" password="s3cret123"
vault kv put secret/app/api-key key="ak_live_xxx123"

# Shut down Vault cleanly
kill -TERM $VAULT_PID
wait $VAULT_PID 2>/dev/null || true
rm -f /tmp/pki_int.csr /tmp/intermediate.cert.pem /tmp/vault.log
