#!/bin/bash

set -e

pip3 install PyYAML==6.0.2 -q

# Step 1: Deploy the fixed provider plugin and corrected config
python3 /solution/build_solution.py

# Step 2: Make the plugin importable
export PYTHONPATH=/app/plugins:${PYTHONPATH:-}

# Step 3: Set pygeoapi environment variables
export PYGEOAPI_CONFIG=/app/config.yml
export PYGEOAPI_OPENAPI=/app/openapi.yml

# Step 4: Generate the OpenAPI document from the config
pygeoapi openapi generate "$PYGEOAPI_CONFIG" --output-file "$PYGEOAPI_OPENAPI"

# Step 5: Start the pygeoapi server
cd /app
python3 -c "
import os, sys
os.environ['PYGEOAPI_CONFIG'] = '/app/config.yml'
os.environ['PYGEOAPI_OPENAPI'] = '/app/openapi.yml'
sys.path.insert(0, '/app/plugins')
from pygeoapi.flask_app import APP
APP.run(host='0.0.0.0', port=5000, debug=False)
" > /tmp/pygeoapi_server.log 2>&1 &
SERVER_PID=$!

# Step 6: Wait for server to be responsive
echo "Waiting for server to start (PID $SERVER_PID)..."
for i in $(seq 1 45); do
    if curl -s -o /dev/null http://localhost:5000/ 2>/dev/null; then
        echo "Server is running on port 5000"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Server failed to start within 45 seconds"
cat /tmp/pygeoapi_server.log 2>/dev/null || true
exit 1
