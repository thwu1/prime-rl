#!/bin/bash
set -euo pipefail


export COSIGN_PASSWORD=""

PIPELINE_DIR=/app/pipeline
PKI_DIR=$PIPELINE_DIR/pki
KEYS_DIR=$PIPELINE_DIR/keys
ATT_DIR=$PIPELINE_DIR/attestations
OFFLINE_DIR=$PIPELINE_DIR/offline
REG_HOST=localhost
REG_PORT=5555

mkdir -p "$PKI_DIR" "$KEYS_DIR" "$ATT_DIR" "$OFFLINE_DIR"

###############################################################################
# 1. Start local OCI registry
###############################################################################
registry -port "$REG_PORT" &
REG_PID=$!
cleanup() { kill "$REG_PID" 2>/dev/null || true; }
trap cleanup EXIT
sleep 2

###############################################################################
# 2. Create container images with crane and push to registry
###############################################################################
mkdir -p /tmp/webapp-layer /tmp/worker-layer

printf '{"app":"webapp","version":"1.0.0","description":"Main web application"}\n' \
  > /tmp/webapp-layer/app.json
printf 'OK\n' > /tmp/webapp-layer/healthz
tar cf /tmp/webapp-layer.tar -C /tmp/webapp-layer .

printf '{"app":"worker","version":"1.0.0","description":"Background worker"}\n' \
  > /tmp/worker-layer/app.json
printf 'OK\n' > /tmp/worker-layer/healthz
tar cf /tmp/worker-layer.tar -C /tmp/worker-layer .

WEBAPP_REF="${REG_HOST}:${REG_PORT}/pipeline/webapp:v1"
WORKER_REF="${REG_HOST}:${REG_PORT}/pipeline/worker:v1"

crane append -f /tmp/webapp-layer.tar -t "$WEBAPP_REF" --insecure
crane append -f /tmp/worker-layer.tar -t "$WORKER_REF" --insecure

WEBAPP_DIGEST=$(crane digest "$WEBAPP_REF" --insecure)
WORKER_DIGEST=$(crane digest "$WORKER_REF" --insecure)

echo "Webapp digest: $WEBAPP_DIGEST"
echo "Worker digest: $WORKER_DIGEST"

###############################################################################
# 3. Rebuild PKI hierarchy with correct EC keys and extensions
###############################################################################

# --- Root CA (ECDSA P-256) ---
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -out "$PKI_DIR/root-ca-key.pem" 2>/dev/null

openssl req -new -x509 -key "$PKI_DIR/root-ca-key.pem" \
  -out "$PKI_DIR/root-ca.pem" -days 365 \
  -subj "/CN=Supply Chain Root CA/O=Pipeline Security" \
  -addext "basicConstraints=critical,CA:true" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# --- Intermediate CA (ECDSA P-256, pathlen:0) ---
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -out "$PKI_DIR/intermediate-ca-key.pem" 2>/dev/null

openssl req -new -key "$PKI_DIR/intermediate-ca-key.pem" \
  -out "$PKI_DIR/intermediate-ca.csr" \
  -subj "/CN=Supply Chain Intermediate CA/O=Pipeline Security"

printf 'basicConstraints=critical,CA:true,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n' \
  > /tmp/intermediate-ext.cnf

openssl x509 -req -in "$PKI_DIR/intermediate-ca.csr" \
  -CA "$PKI_DIR/root-ca.pem" -CAkey "$PKI_DIR/root-ca-key.pem" \
  -out "$PKI_DIR/intermediate-ca.pem" \
  -days 365 -CAcreateserial -extfile /tmp/intermediate-ext.cnf

# --- Leaf signing cert (ECDSA P-256, CA:FALSE, digitalSignature only) ---
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -out "$PKI_DIR/leaf-key.pem" 2>/dev/null

openssl req -new -key "$PKI_DIR/leaf-key.pem" \
  -out "$PKI_DIR/leaf.csr" \
  -subj "/CN=Image Signer/O=Pipeline Security"

printf 'basicConstraints=critical,CA:false\nkeyUsage=critical,digitalSignature\n' \
  > /tmp/leaf-ext.cnf

openssl x509 -req -in "$PKI_DIR/leaf.csr" \
  -CA "$PKI_DIR/intermediate-ca.pem" -CAkey "$PKI_DIR/intermediate-ca-key.pem" \
  -out "$PKI_DIR/leaf.pem" \
  -days 365 -CAcreateserial -extfile /tmp/leaf-ext.cnf

# --- Certificate chain file (intermediate + root, correct order) ---
cat "$PKI_DIR/intermediate-ca.pem" "$PKI_DIR/root-ca.pem" > "$PKI_DIR/chain.pem"

# Verify the chain
openssl verify -CAfile "$PKI_DIR/root-ca.pem" \
  -untrusted "$PKI_DIR/intermediate-ca.pem" "$PKI_DIR/leaf.pem"

echo "PKI hierarchy rebuilt and verified."

###############################################################################
# 4. Import leaf key into cosign format
###############################################################################
cosign import-key-pair \
  --key "$PKI_DIR/leaf-key.pem" \
  --output-key-prefix "$KEYS_DIR/cosign" -y

echo "Cosign key pair imported from leaf key."

###############################################################################
# 5. Sign both images with cosign + annotations
###############################################################################
for REF in "$WEBAPP_REF" "$WORKER_REF"; do
  cosign sign \
    --key "$KEYS_DIR/cosign.key" \
    --certificate "$PKI_DIR/leaf.pem" \
    --certificate-chain "$PKI_DIR/chain.pem" \
    --tlog-upload=false \
    --allow-http-registry \
    --allow-insecure-registry \
    -a "pipeline.version=v1" \
    -a "pipeline.stage=production" \
    -y \
    "$REF"
  echo "Signed: $REF"
done

###############################################################################
# 6. Create and attach SLSA provenance attestations
###############################################################################
python3 -c "
import json, sys
for name, git_ref, invocation_id in [
    ('webapp', 'refs/heads/main', 'pipeline-run-001'),
    ('worker', 'refs/heads/main', 'pipeline-run-002'),
]:
    pred = {
        'builder': {'id': 'https://ci.example.com/pipeline/v1'},
        'buildType': 'https://example.com/container-build/v1',
        'invocation': {
            'configSource': {
                'uri': f'git+https://github.com/example/{name}@{git_ref}',
                'digest': {'sha1': 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'},
                'entryPoint': 'Dockerfile',
            }
        },
        'metadata': {
            'buildInvocationId': invocation_id,
            'buildStartedOn': '2024-06-01T10:00:00Z',
            'buildFinishedOn': '2024-06-01T10:05:00Z',
            'completeness': {
                'parameters': True,
                'environment': True,
                'materials': True,
            },
        },
        'materials': [
            {
                'uri': 'pkg:oci/scratch',
                'digest': {'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'},
            }
        ],
    }
    out = f'$ATT_DIR/slsa-provenance-{name}.json'
    with open(out, 'w') as f:
        json.dump(pred, f, indent=2)
    print(f'Wrote {out}')
"

for NAME in webapp worker; do
  if [ "$NAME" = "webapp" ]; then REF="$WEBAPP_REF"; else REF="$WORKER_REF"; fi

  cosign attest \
    --key "$KEYS_DIR/cosign.key" \
    --predicate "$ATT_DIR/slsa-provenance-${NAME}.json" \
    --type slsaprovenance \
    --tlog-upload=false \
    --allow-http-registry \
    --allow-insecure-registry \
    -y \
    "$REF"
  echo "SLSA attestation attached: $REF"
done

###############################################################################
# 7. Create and attach vulnerability scan attestation (webapp only)
###############################################################################
python3 -c "
import json
pred = {
    'scanner': {'uri': 'https://scanner.example.com/v1', 'version': '2.5.0'},
    'scanResult': {
        'status': 'PASS',
        'vulnerabilities': [],
        'scannedAt': '2024-06-01T10:10:00Z',
    },
}
with open('$ATT_DIR/vuln-scan-webapp.json', 'w') as f:
    json.dump(pred, f, indent=2)
print('Wrote vuln-scan-webapp.json')
"

cosign attest \
  --key "$KEYS_DIR/cosign.key" \
  --predicate "$ATT_DIR/vuln-scan-webapp.json" \
  --type vuln \
  --tlog-upload=false \
  --allow-http-registry \
  --allow-insecure-registry \
  -y \
  "$WEBAPP_REF"

echo "Vuln attestation attached to webapp."

###############################################################################
# 8. Save images for air-gapped verification
###############################################################################
cosign save \
  --dir "$OFFLINE_DIR/webapp" \
  --allow-http-registry \
  --allow-insecure-registry \
  "$WEBAPP_REF"

cosign save \
  --dir "$OFFLINE_DIR/worker" \
  --allow-http-registry \
  --allow-insecure-registry \
  "$WORKER_REF"

echo "Images saved for offline verification."

###############################################################################
# 9. Verify offline
###############################################################################
cosign verify \
  --key "$KEYS_DIR/cosign.pub" \
  --insecure-ignore-tlog \
  --local-image "$OFFLINE_DIR/webapp" > /dev/null

cosign verify \
  --key "$KEYS_DIR/cosign.pub" \
  --insecure-ignore-tlog \
  --local-image "$OFFLINE_DIR/worker" > /dev/null

cosign verify-attestation \
  --key "$KEYS_DIR/cosign.pub" \
  --type slsaprovenance \
  --insecure-ignore-tlog \
  --local-image "$OFFLINE_DIR/webapp" > /dev/null

cosign verify-attestation \
  --key "$KEYS_DIR/cosign.pub" \
  --type slsaprovenance \
  --insecure-ignore-tlog \
  --local-image "$OFFLINE_DIR/worker" > /dev/null

cosign verify-attestation \
  --key "$KEYS_DIR/cosign.pub" \
  --type vuln \
  --insecure-ignore-tlog \
  --local-image "$OFFLINE_DIR/webapp" > /dev/null

echo "All offline verifications passed."

###############################################################################
# 10. Generate audit report
###############################################################################
python3 /solution/generate_audit.py \
  --pki-dir "$PKI_DIR" \
  --keys-dir "$KEYS_DIR" \
  --offline-dir "$OFFLINE_DIR" \
  --webapp-digest "$WEBAPP_DIGEST" \
  --worker-digest "$WORKER_DIGEST" \
  --output "$PIPELINE_DIR/audit-report.json"

echo "Pipeline complete. Audit report at $PIPELINE_DIR/audit-report.json"
