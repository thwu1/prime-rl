#!/bin/bash
set -e

# Creates a deliberately broken supply chain pipeline for diagnosis.
# Issues planted:
# 1. All certs use RSA instead of EC
# 2. Intermediate CA missing pathlen:0 constraint
# 3. Leaf cert has CA:TRUE and keyCertSign (should be CA:FALSE, digitalSignature)
# 4. chain.pem has certs in wrong order (root first)
# 5. Cosign keypair is standalone (not derived from leaf key)
# 6. SLSA attestation stubs missing required fields
# 7. No vuln scan attestation
# 8. Audit report has wrong structure

PKI_DIR=/app/pipeline/pki
KEYS_DIR=/app/pipeline/keys
ATT_DIR=/app/pipeline/attestations
mkdir -p "$PKI_DIR" "$KEYS_DIR" "$ATT_DIR"

# Root CA with RSA (wrong algorithm)
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out "$PKI_DIR/root-ca-key.pem" 2>/dev/null
openssl req -new -x509 -key "$PKI_DIR/root-ca-key.pem" \
  -out "$PKI_DIR/root-ca.pem" -days 365 \
  -subj "/CN=Supply Chain Root CA/O=Pipeline Security" \
  -addext "basicConstraints=critical,CA:true" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# Intermediate CA with RSA, missing pathlen:0
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out "$PKI_DIR/intermediate-ca-key.pem" 2>/dev/null
openssl req -new -key "$PKI_DIR/intermediate-ca-key.pem" \
  -out /tmp/intermediate.csr \
  -subj "/CN=Supply Chain Intermediate CA/O=Pipeline Security"
printf 'basicConstraints=critical,CA:true\nkeyUsage=critical,keyCertSign,cRLSign\n' > /tmp/int-ext.cnf
openssl x509 -req -in /tmp/intermediate.csr \
  -CA "$PKI_DIR/root-ca.pem" -CAkey "$PKI_DIR/root-ca-key.pem" \
  -out "$PKI_DIR/intermediate-ca.pem" -days 365 -CAcreateserial \
  -extfile /tmp/int-ext.cnf

# Leaf cert with RSA, CA:TRUE + keyCertSign (both wrong)
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out "$PKI_DIR/leaf-key.pem" 2>/dev/null
openssl req -new -key "$PKI_DIR/leaf-key.pem" \
  -out /tmp/leaf.csr \
  -subj "/CN=Image Signer/O=Pipeline Security"
printf 'basicConstraints=critical,CA:true\nkeyUsage=critical,keyCertSign\n' > /tmp/leaf-ext.cnf
openssl x509 -req -in /tmp/leaf.csr \
  -CA "$PKI_DIR/intermediate-ca.pem" -CAkey "$PKI_DIR/intermediate-ca-key.pem" \
  -out "$PKI_DIR/leaf.pem" -days 365 -CAcreateserial \
  -extfile /tmp/leaf-ext.cnf

# Chain in wrong order (root first, should be intermediate first)
cat "$PKI_DIR/root-ca.pem" "$PKI_DIR/intermediate-ca.pem" > "$PKI_DIR/chain.pem"

# Standalone cosign keypair (not derived from leaf key - key mismatch)
COSIGN_PASSWORD="" cosign generate-key-pair --output-key-prefix "$KEYS_DIR/cosign"

# Malformed SLSA stubs (missing materials and metadata fields)
printf '{"builder": {"id": "https://ci.example.com/v1"}}\n' > "$ATT_DIR/slsa-provenance-webapp.json"
printf '{"builder": {"id": "https://ci.example.com/v1"}}\n' > "$ATT_DIR/slsa-provenance-worker.json"

# Broken audit report (wrong schema)
printf '{"status": "FAIL", "errors": ["verification_failed", "chain_invalid"]}\n' > /app/pipeline/audit-report.json

# Status note for the agent to find
printf 'Pipeline Status: FAILING\nMultiple verification errors detected in PKI, signatures, and attestations.\nImages have not been pushed to registry.\n' > /app/pipeline/STATUS

# Cleanup build artifacts
rm -f /tmp/intermediate.csr /tmp/leaf.csr /tmp/int-ext.cnf /tmp/leaf-ext.cnf
rm -f "$PKI_DIR"/*.srl
