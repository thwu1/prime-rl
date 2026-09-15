#!/bin/bash

set -e

# Ensure Rust/Verus environment is available
export CARGO_HOME=/opt/cargo
export RUSTUP_HOME=/opt/rustup
export PATH="/opt/verus:/opt/cargo/bin:/usr/local/bin:$PATH"

# Apply verification fixes via computed string transformations
python3 /solution/fix_verification.py

# Verify the fix by running Verus
echo "Running Verus verification..."
verus /app/verified_algorithms.rs
VERUS_EXIT=$?

if [ $VERUS_EXIT -eq 0 ]; then
    echo "Verification succeeded - all proof obligations discharged."
else
    echo "Verification failed with exit code $VERUS_EXIT"
    exit 1
fi

# Sanity check: no assume(false) in the file
if grep -qP 'assume\s*\(false\)' /app/verified_algorithms.rs; then
    echo "ERROR: File contains assume(false) - this is not a valid fix."
    exit 1
fi

echo "Solution complete."
