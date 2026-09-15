#!/usr/bin/env bash

set -euo pipefail

# Copy the solved file over the original
cp /solution/MultiLimbArith_solved.v /app/MultiLimbArith.v

# Verify it compiles
coqc -Q /app "" /app/MultiLimbArith.v

echo "Solution applied and verified successfully."
