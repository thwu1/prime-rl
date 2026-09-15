#!/bin/bash

pip3 install pytest==8.3.4 confluent-kafka==2.3.0 -q

# Start Kafka
/usr/local/bin/start-kafka.sh

# Clean up any pre-existing topics to ensure fresh state
KAFKA_HOME=${KAFKA_HOME:-/opt/kafka}
for topic in order-commands order-events customer-state saga-state notifications dead-letter; do
    "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server localhost:9092 --delete --topic "$topic" 2>/dev/null || true
done
sleep 3

# Run topic setup if it exists
if [ -f /app/setup_topics.sh ]; then
    bash /app/setup_topics.sh
fi

# Run tests
pytest /tests/test_state.py -v --tb=short
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
