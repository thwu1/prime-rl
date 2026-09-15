#!/bin/bash

set -e

# Install runtime dependencies
pip3 install confluent-kafka==2.3.0 -q

# Start Kafka
/usr/local/bin/start-kafka.sh

# Deploy solution files
cp /solution/config.py /app/config.py
cp /solution/models.py /app/models.py
cp /solution/setup_topics.sh /app/setup_topics.sh
cp /solution/processor.py /app/processor.py
cp /solution/saga.py /app/saga.py
cp /solution/outbox.py /app/outbox.py
chmod +x /app/setup_topics.sh

# Create topics
bash /app/setup_topics.sh

echo "Solution deployed successfully."
