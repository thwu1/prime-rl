#!/bin/bash

set -e

# Deploy the SPIR-V binary tool implementation
cp /solution/spirv_tool_impl.py /app/spirv_tool.py

# Verify all subcommands produce valid output
echo "=== Verifying analyze ==="
python3 /app/spirv_tool.py analyze /app/modules/compute.spv

echo "=== Verifying strip-dead ==="
python3 /app/spirv_tool.py strip-dead /app/modules/compute.spv /tmp/verify_strip.spv
spirv-val /tmp/verify_strip.spv
echo "strip-dead: spirv-val passed"

echo "=== Verifying compact ==="
python3 /app/spirv_tool.py compact /tmp/verify_strip.spv /tmp/verify_compact.spv
spirv-val /tmp/verify_compact.spv
echo "compact: spirv-val passed"

echo "=== Verifying merge ==="
python3 /app/spirv_tool.py merge /app/modules/merge_a.spv /app/modules/merge_b.spv /tmp/verify_merge.spv
spirv-val /tmp/verify_merge.spv
echo "merge: spirv-val passed"

echo "=== All verifications passed ==="
