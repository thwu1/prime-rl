#!/bin/bash
# Architecture Governance Pipeline
# Parses dependency data from heterogeneous sources, computes structural
# quality metrics, and generates compliance reports.

set -euo pipefail

DATA_DIR="/app/data"
PIPELINE_DIR="/app/pipeline"
RESULTS_DIR="/app/results"
TMP_DIR="/tmp/governance"

mkdir -p "$RESULTS_DIR" "$TMP_DIR"

echo "=== Architecture Governance Pipeline ==="
echo ""
echo "Step 1: Parsing dependency graph from DOT format..."
python3 "$PIPELINE_DIR/parse_graph.py" \
    "$DATA_DIR/dependencies.dot" \
    "$TMP_DIR/edges.json"

echo ""
echo "Step 2: Running architecture analysis..."
python3 "$PIPELINE_DIR/analyze.py" \
    "$TMP_DIR/edges.json" \
    "$DATA_DIR/components.db" \
    "$DATA_DIR/governance.yaml" \
    "$RESULTS_DIR"

echo ""
echo "=== Pipeline complete ==="
