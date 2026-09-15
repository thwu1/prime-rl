#!/bin/bash
# Generate a random flag at runtime (not baked into Docker image)
mkdir -p /app/secrets
python3 -c "import os; print('FLAG{' + os.urandom(16).hex() + '}')" > /app/secrets/flag.txt

# Start the ground station server
/app/ground_station &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 30); do
    if nc -z 127.0.0.1 9090 2>/dev/null; then
        break
    fi
    sleep 0.5
done

# Remove flag file - it is now only in server memory
rm -f /app/secrets/flag.txt

# Keep container alive
wait $SERVER_PID 2>/dev/null
exec tail -f /dev/null
