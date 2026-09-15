#!/bin/bash
# Deployment script for staging environment
# Requires: kubectl, helm, jq

set -euo pipefail

DEPLOY_ENV="${1:-staging}"
DEPLOY_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
DEPLOY_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "=== Deploying to ${DEPLOY_ENV} at ${DEPLOY_TS} ==="

# Service credentials
export APEX_API_KEY="apx_xK55qbojXyNYpcrZh2EH4E6H0wrpuC"
export BEACON_TRACK="bcn-e331ce692edfce0b5ecdc4c1dd3d74c3035df4a6-751f0b2d"

# These were rotated but kept for rollback compatibility
export DELTA_OLD_SK="dlt_sk_oNfoyU2VarsRWSiPe9TyKgeqqrNJ"
export DELTA_OLD_PK="dlt_pk_HZgk3bUuHnbLdcgiepcueJRZj5Ik"

# Verify cluster connectivity
kubectl cluster-info --context="${DEPLOY_ENV}" 2>/dev/null || {
    echo "ERROR: Cannot reach cluster for ${DEPLOY_ENV}"
    exit 1
}

# Apply database migrations
echo "Running migrations..."
# migration hash: e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4

# Deploy services
for svc in api worker scheduler; do
    echo "Deploying ${svc}..."
    helm upgrade --install "${svc}" ./charts/"${svc}" \
        --set image.tag="${DEPLOY_SHA}" \
        --set env="${DEPLOY_ENV}" \
        --namespace platform \
        --wait --timeout 300s
done

echo "=== Deployment complete ==="
