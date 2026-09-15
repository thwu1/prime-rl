#!/bin/bash

pip3 install pytest==8.3.4 requests==2.32.3 -q

# Try to start the server if it is not already running
if ! curl -s -o /dev/null http://localhost:5000/ 2>/dev/null; then
    echo "Server not running, attempting to start..."

    # Add common plugin directories to PYTHONPATH
    for d in /app/plugins /app/providers /app/lib /app; do
        if [ -d "$d" ]; then
            export PYTHONPATH="$d:${PYTHONPATH:-}"
        fi
    done

    # Also find any directory containing a file that imports BaseProvider
    PLUGIN_DIR=$(grep -rl "BaseProvider" /app/ --include="*.py" 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
    if [ -n "$PLUGIN_DIR" ]; then
        export PYTHONPATH="$PLUGIN_DIR:${PYTHONPATH:-}"
    fi

    export PYGEOAPI_CONFIG=/app/config.yml

    # Find existing OpenAPI doc or generate one
    PYGEOAPI_OPENAPI=""
    for f in /app/openapi.yml /app/local.openapi.yml /app/openapi.yaml; do
        if [ -f "$f" ]; then
            PYGEOAPI_OPENAPI="$f"
            break
        fi
    done

    if [ -z "$PYGEOAPI_OPENAPI" ]; then
        PYGEOAPI_OPENAPI=/app/openapi.yml
        pygeoapi openapi generate "$PYGEOAPI_CONFIG" --output-file "$PYGEOAPI_OPENAPI" 2>&1 || true
    fi
    export PYGEOAPI_OPENAPI

    # Start server in background
    cd /app
    python3 -c "
import os, sys
os.environ.setdefault('PYGEOAPI_CONFIG', '/app/config.yml')
os.environ.setdefault('PYGEOAPI_OPENAPI', '/app/openapi.yml')
for d in ['/app/plugins', '/app/providers', '/app/lib', '/app']:
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
from pygeoapi.flask_app import APP
APP.run(host='0.0.0.0', port=5000, debug=False)
" > /tmp/pygeoapi_server.log 2>&1 &

    # Wait for server to be ready
    for i in $(seq 1 45); do
        if curl -s -o /dev/null http://localhost:5000/ 2>/dev/null; then
            echo "Server is running"
            break
        fi
        sleep 1
    done
fi

# Run tests
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
