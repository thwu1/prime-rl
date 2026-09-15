#!/bin/bash

# Copy server implementation to /app/
cp /solution/server.py /app/server.py

# Create run.sh
cat > /app/run.sh << 'RUNEOF'
#!/bin/bash
cd /app
exec python3 server.py
RUNEOF
chmod +x /app/run.sh
