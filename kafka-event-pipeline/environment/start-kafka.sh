#!/bin/bash
KAFKA_HOME=${KAFKA_HOME:-/opt/kafka}

# Check if already running
if pgrep -f "kafka.Kafka" > /dev/null 2>&1; then
    echo "Kafka is already running"
    exit 0
fi

# Start Kafka in daemon mode
"$KAFKA_HOME/bin/kafka-server-start.sh" -daemon "$KAFKA_HOME/config/kraft/server.properties"

# Wait for Kafka to be ready
echo "Waiting for Kafka to start..."
for i in $(seq 1 60); do
    if "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server localhost:9092 --list > /dev/null 2>&1; then
        echo "Kafka is ready"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Kafka failed to start within 60 seconds"
exit 1
