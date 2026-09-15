#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Step 1: Render Helm chart policies
helm template app-policies /app/policies-chart/ > /tmp/helm-policies.yaml

# Step 2: Parse endpoint state from Cilium JSON format
jq '[.[] | {
  name: .status["external-identifiers"]["container-name"],
  ip: .status.networking.addressing[0].ipv4,
  labels: ([.status.identity.labels[] | select(startswith("k8s:")) | select(startswith("k8s:io.cilium.") | not) | select(startswith("k8s:io.kubernetes.") | not) | ltrimstr("k8s:") | split("=") | {(.[0]): .[1]}] | add)
}]' /app/endpoint-state.json > /tmp/endpoints.json

# Step 3: Run policy evaluation engine
python3 /solution/engine.py
