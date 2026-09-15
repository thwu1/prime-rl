#!/bin/bash

# Deploy the Nuitka user plugin that handles all standalone compilation issues
cp /solution/nuitka_plugin.py /app/nuitka_plugin.py

# Compile the application in standalone mode with the plugin
cd /app
python3 -m nuitka --mode=standalone --user-plugin=nuitka_plugin.py main.py

# Verify outputs match
echo "=== CPython output ==="
python3 main.py

echo ""
echo "=== Standalone output ==="
BINARY=""
for name in main.bin main; do
    if [ -x "main.dist/$name" ]; then
        BINARY="main.dist/$name"
        break
    fi
done

if [ -z "$BINARY" ]; then
    BINARY=$(find main.dist -maxdepth 1 -type f -executable ! -name '*.so' ! -name 'lib*' | head -1)
fi

if [ -n "$BINARY" ]; then
    cd main.dist && ./"$(basename "$BINARY")"
else
    echo "ERROR: No executable found in main.dist/"
    exit 1
fi
