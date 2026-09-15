#!/bin/bash

# Step 1: Fix the 5 bugs in the resolver
python3 /solution/fix_resolver.py

# Step 2: Install the deployment analyzer
cp /solution/analyze_deployment.py /app/analyze_deployment.py

# Step 3: Verify resolver works for all configs
echo "=== Verifying app config ==="
python3 /app/resolve.py app --base-dir /app --hostname testhost | python3 -m json.tool > /dev/null
echo "=== Verifying web_only config ==="
python3 /app/resolve.py web_only --base-dir /app --hostname testhost | python3 -m json.tool > /dev/null
echo "=== Verifying data config ==="
python3 /app/resolve.py data --base-dir /app --hostname testhost | python3 -m json.tool > /dev/null

# Step 4: Verify analyzer works
echo "=== Verifying deployment analyzer ==="
python3 /app/analyze_deployment.py --base-dir /app | python3 -m json.tool > /dev/null

echo "All fixes applied and analyzer verified."
