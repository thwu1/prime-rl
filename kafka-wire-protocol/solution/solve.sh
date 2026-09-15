#!/bin/bash

# Deploy the Kafka broker implementation
cp /solution/broker.py /app/broker.py

# Create the launcher script
cat > /app/run.sh << 'RUNEOF'
#!/bin/bash
exec python3 /app/broker.py
RUNEOF
chmod +x /app/run.sh
