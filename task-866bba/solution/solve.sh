#!/bin/bash

set -euo pipefail

export COSIGN_PASSWORD=""
cd /app

###############################################################################
# Step 1: Identify compromised artifact by comparing build outputs to deployed
###############################################################################
echo "=== Comparing build outputs to deployed artifacts ==="
for f in build_output/*.bin; do
    name=$(basename "$f")
    if ! diff -q "build_output/$name" "artifacts/$name" > /dev/null 2>&1; then
        echo "COMPROMISED: $name"
    else
        echo "OK: $name"
    fi
done

###############################################################################
# Step 2: Generate cosign key pairs for each team
###############################################################################
mkdir -p /app/keys
for team in engineering security release; do
    cosign generate-key-pair --output-key-prefix "/app/keys/$team"
done

###############################################################################
# Step 3: Sign each canonical build output per policy using cosign sign-blob
###############################################################################
mkdir -p /app/bundles

sign_artifact() {
    local artifact="$1"
    local signer="$2"
    cosign sign-blob \
        --key "/app/keys/${signer}.key" \
        --bundle "/app/bundles/${artifact}.${signer}.bundle" \
        --tlog-upload=false \
        --yes \
        "/app/build_output/${artifact}"
}

# api-server.bin: engineering
sign_artifact api-server.bin engineering

# auth-module.bin: engineering, security
sign_artifact auth-module.bin engineering
sign_artifact auth-module.bin security

# data-pipeline.bin: engineering
sign_artifact data-pipeline.bin engineering

# crypto-lib.bin: engineering, security, release
sign_artifact crypto-lib.bin engineering
sign_artifact crypto-lib.bin security
sign_artifact crypto-lib.bin release

# monitoring-agent.bin: engineering, release
sign_artifact monitoring-agent.bin engineering
sign_artifact monitoring-agent.bin release

###############################################################################
# Step 4: Create in-toto attestation statements and sign them as blobs
###############################################################################
mkdir -p /app/attestations
python3 /solution/create_attestations.py

###############################################################################
# Step 5: Create correct verify.sh and run verification against deployed artifacts
###############################################################################
python3 /solution/write_verify.py
chmod +x /app/verify.sh
/app/verify.sh
