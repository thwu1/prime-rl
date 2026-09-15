#!/bin/bash

# Fix the broken broker configuration
python3 /solution/fix_broker.py || { echo "ERROR: fix_broker.py failed"; exit 1; }

# Format KRaft storage with a generated cluster ID
CLUSTER_ID=$(/app/kafka/bin/kafka-storage.sh random-uuid)
/app/kafka/bin/kafka-storage.sh format -t "$CLUSTER_ID" -c /app/kafka/config/kraft/server.properties --ignore-formatted

# Start the broker in background
export KAFKA_HEAP_OPTS="-Xmx512M -Xms256M"
/app/kafka/bin/kafka-server-start.sh /app/kafka/config/kraft/server.properties > /tmp/kafka-broker.log 2>&1 &
BROKER_PID=$!

# Wait for broker to be ready
READY=false
for i in $(seq 1 90); do
    if nc -z localhost 9092 2>/dev/null; then
        READY=true
        break
    fi
    if ! kill -0 $BROKER_PID 2>/dev/null; then
        echo "ERROR: Broker process died"
        tail -50 /tmp/kafka-broker.log
        exit 1
    fi
    sleep 1
done

if [ "$READY" != "true" ]; then
    echo "ERROR: Broker did not start within 90 seconds"
    tail -50 /tmp/kafka-broker.log
    exit 1
fi

sleep 5

# Set up topics, client configs, evaluation deliverables, and verification
python3 /solution/setup_cluster.py
