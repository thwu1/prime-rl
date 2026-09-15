#!/bin/bash

pip3 install pytest==8.3.4 -q

# Ensure lean/lake are available; fallback install if Docker layer is missing
if ! command -v lake &> /dev/null; then
    echo "lake not found in PATH, installing Lean 4.16.0 directly..."
    curl -sL "https://github.com/leanprover/lean4/releases/download/v4.16.0/lean-4.16.0-linux.zip" -o /tmp/lean.zip
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/lean.zip').extractall('/opt')"
    chmod -R +x /opt/lean-4.16.0-linux/bin/
    rm -f /tmp/lean.zip
    export PATH="/opt/lean-4.16.0-linux/bin:$PATH"
fi

# Run lake build and capture output + exit code
cd /app
lake build > /tmp/lean_build_output.txt 2>&1
BUILD_EXIT=$?
echo $BUILD_EXIT > /tmp/lean_build_exitcode.txt
cat /tmp/lean_build_output.txt

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
