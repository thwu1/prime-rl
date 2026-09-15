#!/bin/bash
# Start the FHIR R4 mock server in the background
# Kill any existing server first to avoid port conflicts
pkill -f "python3 /app/fhir_server.py" 2>/dev/null
sleep 1

cd /app
nohup python3 /app/fhir_server.py > /tmp/fhir_server.log 2>&1 &
FHIR_PID=$!
disown $FHIR_PID 2>/dev/null
echo "$FHIR_PID" > /tmp/fhir_server.pid

# Wait for server to be ready
for i in $(seq 1 30); do
    if curl -s http://localhost:8080/fhir/metadata > /dev/null 2>&1; then
        echo "FHIR server ready on port 8080 (PID: $FHIR_PID)"
        exit 0
    fi
    sleep 1
done

echo "ERROR: FHIR server failed to start within 30 seconds"
cat /tmp/fhir_server.log 2>/dev/null
exit 1
