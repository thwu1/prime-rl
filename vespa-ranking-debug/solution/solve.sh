#!/usr/bin/env bash

set -e

# Read the competing proposals and business requirements
echo "=== Business Requirements ==="
cat /app/business_requirements.md

echo ""
echo "=== Evaluating Proposal A ==="
cat /app/proposals/proposal_alpha.md

echo ""
echo "=== Evaluating Proposal B ==="
cat /app/proposals/proposal_beta.md

echo ""
echo "=== Evaluating Proposal C ==="
cat /app/proposals/proposal_gamma.md

echo ""
echo "=== Reading scoring weights ==="
cat /app/application/constants/scoring_weights.json

echo ""
echo "=== Synthesizing correct ranking schema ==="
python3 /solution/create_schema.py

echo ""
echo "=== Final schema ==="
cat /app/application/schemas/product.sd
