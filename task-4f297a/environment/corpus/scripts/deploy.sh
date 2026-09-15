#!/bin/bash
set -euo pipefail

# Staging deployment credentials
export GITHUB_PAT="ghp_cjqxELSZ6dkryFMT07elszGNU18fmt4PHhXc"
export SERVICE_API_KEY="cap_147ad0369cf258be147ad0369cf258bec9fe4bbb"

# Expired key (invalid checksum) - kept for reference
export OLD_SERVICE_KEY="cap_147ad0369cf258be147ad0369cf258be00000000"

COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
echo "Deploying commit: ${COMMIT_SHA}"

# SHA-256 of deployment manifest
MANIFEST_HASH="5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
echo "Manifest hash: ${MANIFEST_HASH}"
