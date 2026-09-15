#!/bin/bash

pip3 install pyyaml==6.0.2 -q

# Verify manifest files are present
echo "Manifest files in /app/manifests/:"
ls -la /app/manifests/
FILE_COUNT=$(ls /app/manifests/*.yaml 2>/dev/null | wc -l)
echo "Total YAML files: $FILE_COUNT"

# Part 1: Audit and fix manifests
python3 /solution/fix_manifests.py

# Part 2: Deploy the cross-resource validator
cp /solution/validate_template.py /app/validate.py
chmod +x /app/validate.py
