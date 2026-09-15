#!/bin/bash

# Prepare directories
mkdir -p /app/exploits/findings /app/captures

# Copy exploit scripts and hardened server to expected locations
cp /solution/exploit_connect_spoofing.py /app/exploits/
cp /solution/exploit_embedded_candidates.py /app/exploits/
cp /solution/exploit_sdp_update.py /app/exploits/
cp /solution/exploit_type_confusion.py /app/exploits/
cp /solution/server_hardened.py /app/voicelink/server_hardened.py

wait_for_port() {
    local port=$1
    local max_tries=15
    local i=0
    while [ $i -lt $max_tries ]; do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',$port)); s.close()" 2>/dev/null; then
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

kill_port() {
    local port=$1
    local pid
    pid=$(lsof -ti tcp:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null
        sleep 1
    fi
}

# Kill any stale server on port 9877
kill_port 9877

# Start the original server
python3 /app/voicelink/server.py &
SERVER_PID=$!
if ! wait_for_port 9877; then
    echo "ERROR: Original server failed to start"
    exit 1
fi

# Run each exploit against the original server
PASS=0
FAIL=0

for exploit in /app/exploits/exploit_*.py; do
    name=$(basename "$exploit" .py | sed 's/exploit_//')
    echo "=== Running exploit: ${name} ==="
    if python3 "$exploit"; then
        PASS=$((PASS + 1))
        echo "  -> PASS"
    else
        FAIL=$((FAIL + 1))
        echo "  -> FAIL"
    fi
done

echo ""
echo "=== Exploit results: $PASS passed, $FAIL failed ==="

# Generate pcap capture files
echo ""
echo "=== Generating pcap capture files ==="
python3 /solution/pcap_writer.py /app/captures 9877

# Stop original server
kill "$SERVER_PID" 2>/dev/null
wait "$SERVER_PID" 2>/dev/null || true
sleep 1

# Ensure port is actually free
kill_port 9877

# Backup findings before running exploits against hardened server,
# because exploit scripts overwrite findings files even when they fail
cp -r /app/exploits/findings /tmp/findings_backup 2>/dev/null || true

# Start hardened server and validate
echo ""
echo "=== Starting hardened server ==="
VLSP_PORT=9877 python3 /app/voicelink/server_hardened.py &
HARDENED_PID=$!
if ! wait_for_port 9877; then
    echo "ERROR: Hardened server failed to start"
    FAIL=$((FAIL + 1))
fi

echo "=== Running conformance tests against hardened server ==="
if python3 /app/voicelink/conformance.py; then
    echo "  -> Conformance PASSED"
else
    echo "  -> Conformance FAILED"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "=== Verifying exploits fail against hardened server ==="
for exploit in /app/exploits/exploit_*.py; do
    name=$(basename "$exploit")
    if python3 "$exploit" 2>/dev/null; then
        echo "  $name: UNEXPECTED SUCCESS (should have been rejected)"
        FAIL=$((FAIL + 1))
    else
        echo "  $name: correctly rejected"
    fi
done

# Restore findings that were overwritten by exploit runs against hardened server
if [ -d /tmp/findings_backup ]; then
    cp /tmp/findings_backup/* /app/exploits/findings/ 2>/dev/null || true
    rm -rf /tmp/findings_backup
fi

# Clean up
kill "$HARDENED_PID" 2>/dev/null
wait "$HARDENED_PID" 2>/dev/null || true

echo ""
echo "Final results: $PASS exploit passes, $FAIL issues"
[ $FAIL -eq 0 ]
