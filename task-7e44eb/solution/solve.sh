#!/bin/bash

# Ensure lean/lake are available; fallback install if Docker layer is missing
if ! command -v lake &> /dev/null; then
    echo "lake not found in PATH, installing Lean 4.16.0 directly..."
    curl -sL "https://github.com/leanprover/lean4/releases/download/v4.16.0/lean-4.16.0-linux.zip" -o /tmp/lean.zip
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/lean.zip').extractall('/opt')"
    chmod -R +x /opt/lean-4.16.0-linux/bin/
    rm -f /tmp/lean.zip
    export PATH="/opt/lean-4.16.0-linux/bin:$PATH"
fi

# Generate the complete solution Lean file
python3 /solution/write_solution.py

# Build to verify
cd /app && lake build
