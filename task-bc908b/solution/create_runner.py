#!/usr/bin/env python3

"""Generate /app/run_fuzzer.sh that orchestrates Schemathesis + targeted fault analysis."""

import os
import stat

runner = r'''#!/bin/bash
BASE_URL="${1:-http://localhost:5000}"

# Register and obtain API key via curl + jq
REGISTER_RESP=$(curl -sf -X POST "$BASE_URL/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"st_runner@test.com","password":"Secure!123","name":"ST Runner"}')

API_KEY=$(echo "$REGISTER_RESP" | jq -r '.api_key // empty')

if [ -z "$API_KEY" ]; then
    # If registration failed (e.g. email taken), try login
    LOGIN_RESP=$(curl -sf -X POST "$BASE_URL/api/v1/auth/login" \
      -H "Content-Type: application/json" \
      -d '{"email":"st_runner@test.com","password":"Secure!123"}')
    API_KEY=$(echo "$LOGIN_RESP" | jq -r '.api_key // empty')
fi

if [ -z "$API_KEY" ]; then
    echo "ERROR: Failed to obtain API key"
    exit 1
fi

echo "API Key obtained: ${API_KEY:0:8}..."

# Create output directories
mkdir -p /app/results/schemathesis_output

# Phase 1: Run Schemathesis with stateful link-based testing
echo "=== Phase 1: Schemathesis property-based testing ==="
schemathesis run /app/spec/openapi.json \
  --base-url "$BASE_URL" \
  --header "X-API-Key: $API_KEY" \
  --stateful=links \
  --hypothesis-max-examples=50 \
  --cassette-path /app/results/schemathesis_output/cassette.yaml \
  2>&1 | tee /app/results/schemathesis_output/run_output.txt || true

# Ensure schemathesis output directory has content even if cassette flag failed
if [ ! -s /app/results/schemathesis_output/run_output.txt ]; then
    schemathesis run /app/spec/openapi.json \
      --base-url "$BASE_URL" \
      --header "X-API-Key: $API_KEY" \
      --stateful=links \
      --hypothesis-max-examples=50 \
      2>&1 | tee /app/results/schemathesis_output/run_output.txt || true
fi

# Phase 2: Supplementary targeted fault analysis and report generation
echo "=== Phase 2: Targeted fault analysis ==="
python3 /app/fault_analyzer.py "$BASE_URL" "$API_KEY"
'''

path = '/app/run_fuzzer.sh'
with open(path, 'w') as f:
    f.write(runner)

st = os.stat(path)
os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
