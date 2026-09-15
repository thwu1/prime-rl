#!/usr/bin/env bash

pip3 install pyyaml==6.0.2 -q

# Replace the broken evaluator with the corrected implementation
cp /solution/netpol_evaluator.py /app/netpol-eval
chmod +x /app/netpol-eval

# Verify the evaluator works across all manifest formats
echo "Running sanity checks..."

# Check plain YAML scenario
RESULT=$(/app/netpol-eval /app/manifests/scenario-01 alpha/web beta/api 8080 TCP)
if [ "$RESULT" = "ALLOW" ]; then
    echo "Plain YAML: PASS"
else
    echo "Plain YAML: FAIL (expected ALLOW, got '$RESULT')"
    exit 1
fi

# Check kustomize overlay scenario
RESULT=$(/app/netpol-eval /app/manifests/scenario-10 mesh-control/envoy-proxy mesh-data/worker-a 15001 TCP)
if [ "$RESULT" = "ALLOW" ]; then
    echo "Kustomize overlay: PASS"
else
    echo "Kustomize overlay: FAIL (expected ALLOW, got '$RESULT')"
    exit 1
fi

# Check split YAML files scenario
RESULT=$(/app/netpol-eval /app/manifests/scenario-11 edge/ingress-gw core/app 8080 TCP)
if [ "$RESULT" = "ALLOW" ]; then
    echo "Split YAML files: PASS"
else
    echo "Split YAML files: FAIL (expected ALLOW, got '$RESULT')"
    exit 1
fi

echo "All sanity checks passed."
