#!/bin/bash

set -e

# Install solution dependencies
pip3 install pyyaml==6.0.2 -q

# Run the policy generation script
python3 /solution/generate_policies.py

echo "Solution complete. Artifacts written to /app/analysis/ and /app/policies/"
