#!/bin/bash

# Deploy the SPIR-V binary surgeon tool
cp /solution/spirv_surgeon.py /app/spirv_surgeon.py
chmod +x /app/spirv_surgeon.py

# Verify the tool works on each provided module
python3 /app/spirv_surgeon.py analyze /app/modules/vertex.spv > /dev/null
python3 /app/spirv_surgeon.py analyze /app/modules/fragment.spv > /dev/null
python3 /app/spirv_surgeon.py analyze /app/modules/compute.spv > /dev/null
python3 /app/spirv_surgeon.py analyze /app/modules/custom.spv > /dev/null

# Verify remap produces valid SPIR-V
python3 /app/spirv_surgeon.py remap /app/modules/vertex.spv /tmp/test_remap.spv /app/remap_config.json
spirv-val /tmp/test_remap.spv

# Verify strip-debug produces valid SPIR-V
python3 /app/spirv_surgeon.py strip-debug /app/modules/vertex.spv /tmp/test_strip.spv
spirv-val /tmp/test_strip.spv

echo "Solution deployed and verified."
