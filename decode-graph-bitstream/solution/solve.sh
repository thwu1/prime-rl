#!/bin/bash

# Build the diagnostic toolkit with cmake
cd /app/tools
mkdir -p build
cd build
cmake .. 2>&1
make -j$(nproc) 2>&1

echo "=== Header Info ==="
/app/tools/build/header_info /app/data/graph.bin

echo ""
echo "=== Study bitstream.c to understand encoding algorithms ==="
echo "Key functions to study:"
echo "  wgef_br_read_gamma    — Elias gamma code"
echo "  wgef_br_read_zeta     — Boldi-Vigna zeta_k code (uses minimal binary)"
echo "  wgef_br_read_minimal_binary — minimal binary sub-code"
echo ""

echo "=== EF Dump (key fields via jq) ==="
/app/tools/build/ef_dump /app/data/graph.bin > /tmp/ef_info.json

# Extract layout parameters with jq
NODE_DATA_START=$(jq '.layout.node_data_start_bit' /tmp/ef_info.json)
NODES=$(jq '.header.nodes' /tmp/ef_info.json)
ZETA_K=$(jq '.header.zeta_k' /tmp/ef_info.json)
echo "Node data starts at bit: $NODE_DATA_START"
echo "Nodes: $NODES, Zeta K: $ZETA_K"

# Extract first few offsets with jq for validation
echo "First 5 offsets: $(jq '[.offsets[:5][]]' /tmp/ef_info.json)"

# Probe node 0 to validate understanding of node data format
OFFSET_0=$(jq '.offsets[0]' /tmp/ef_info.json)
PROBE_POS=$((NODE_DATA_START + OFFSET_0))
echo ""
echo "=== Probing node 0 degree at bit $PROBE_POS ==="
/app/tools/build/bitprobe /app/data/graph.bin $PROBE_POS gamma

# Run the full decoder
cd /app
python3 /solution/decoder.py
