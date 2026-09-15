#!/bin/bash

# Install scala-cli if not present
if ! command -v scala-cli &> /dev/null; then
    echo "Installing scala-cli..."
    curl -sSfL "https://github.com/VirtusLab/scala-cli/releases/latest/download/scala-cli-x86_64-pc-linux.gz" \
        -o /tmp/sc.gz
    gzip -d /tmp/sc.gz && chmod +x /tmp/sc && mv /tmp/sc /usr/local/bin/scala-cli
    echo "scala-cli installed."
fi

cd /app

# Verify source files exist
echo "=== Checking source files ==="
ls -la /app/src/

# Apply all fixes using the Python helper
echo "=== Applying fixes ==="
python3 /solution/fix.py
FIX_RC=$?
if [ $FIX_RC -ne 0 ]; then
    echo "Fix script failed with exit code $FIX_RC"
    exit $FIX_RC
fi

# Verify the fix
echo "=== Compiling ==="
scala-cli compile /app/src/
COMPILE_RC=$?
if [ $COMPILE_RC -ne 0 ]; then
    echo "Compilation failed with exit code $COMPILE_RC"
    exit $COMPILE_RC
fi

echo "=== Running ==="
scala-cli run /app/src/
