#!/bin/bash
KAFKA_HOME=${KAFKA_HOME:-/opt/kafka}
BS=localhost:9092

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic order-commands --partitions 6 --replication-factor 1 \
    --config retention.ms=604800000 \
    --config cleanup.policy=delete

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic order-events --partitions 6 --replication-factor 1 \
    --config cleanup.policy=delete \
    --config retention.ms=604800000

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic customer-state --partitions 1 --replication-factor 1 \
    --config cleanup.policy=delete \
    --config retention.ms=604800000

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic saga-state --partitions 6 --replication-factor 1 \
    --config cleanup.policy=compact \
    --config retention.ms=86400000

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic notifications --partitions 3 --replication-factor 1 \
    --config cleanup.policy=delete \
    --config retention.ms=86400000

"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server "$BS" --create --if-not-exists \
    --topic dead-letter --partitions 1 --replication-factor 1 \
    --config cleanup.policy=delete \
    --config retention.ms=86400000

echo "All topics created."
