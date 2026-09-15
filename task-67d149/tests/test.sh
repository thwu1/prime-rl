#!/bin/bash

pip3 install pytest==8.3.2 grpcio==1.66.2 grpcio-tools==1.66.2 -q

# Compile proto stubs for test use (independent of agent's compilation)
python3 -m grpc_tools.protoc -I/app --python_out=/tests --grpc_python_out=/tests /app/interface.proto

# Kill any leftover server from solve.sh
pkill -f "python3 /app/server.py" 2>/dev/null || true
sleep 2

# Start the agent's gRPC server
chmod +x /app/start_server.sh 2>/dev/null
/app/start_server.sh &
SERVER_PID=$!

# Wait for server to be ready (up to 30 seconds)
for i in $(seq 1 30); do
    if python3 -c "import socket; s=socket.socket(); s.connect(('localhost', 50051)); s.close()" 2>/dev/null; then
        break
    fi
    sleep 1
done

cd /app
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Cleanup
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
