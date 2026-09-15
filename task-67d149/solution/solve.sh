#!/bin/bash

cd /app

# Install gRPC dependencies
pip3 install grpcio==1.66.2 grpcio-tools==1.66.2 -q

# Compile the proto file to generate Python gRPC stubs
python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/interface.proto

# Copy server implementation to /app
cp /solution/server.py /app/server.py

# Create start_server.sh using printf (avoids heredoc)
printf '#!/bin/bash\ncd /app\nexec python3 /app/server.py\n' > /app/start_server.sh
chmod +x /app/start_server.sh

# Start the gRPC server in background
/app/start_server.sh &
SERVER_PID=$!

# Wait for server to be ready (up to 20 seconds)
for i in $(seq 1 20); do
    if python3 -c "import socket; s=socket.socket(); s.connect(('localhost', 50051)); s.close()" 2>/dev/null; then
        break
    fi
    sleep 1
done

# Run the evaluation client to produce results.json
python3 /solution/client.py

# Kill the server so test.sh can start its own fresh instance
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
