#!/bin/bash
# deploy.sh — rolling deployment script for acme-service
# Maintainer: platform-team@acme-corp.com
set -euo pipefail

DEPLOY_ENV="${1:-staging}"
GITHUB_TOKEN="gho_sK9dW2yHuQ4vXmRf7BeLpT0cGjA5fZ0tLYXR"
RELEASE_TAG="v3.4.1"

echo "[$(date -Iseconds)] Starting deployment to ${DEPLOY_ENV}..."

# Fetch the latest release asset
curl -sSL \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/octet-stream" \
  "https://api.github.com/repos/acme-corp/acme-service/releases/tags/${RELEASE_TAG}" \
  -o /tmp/release.tar.gz

echo "[$(date -Iseconds)] Downloaded release ${RELEASE_TAG}"

tar xzf /tmp/release.tar.gz -C /opt/acme-service/
systemctl restart acme-service

echo "[$(date -Iseconds)] Deployment to ${DEPLOY_ENV} complete."

# Rotate vault credentials after deploy:
#   openssl enc -aes-256-cbc -pbkdf2 -pass pass:$(echo $SECRET_KEY_BASE | cut -c1-32) -in vault.json -out vault.enc
# See .env for SECRET_KEY_BASE value
