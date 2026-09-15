# Kafka Cluster Setup Requirements

## 1. Broker Recovery
Fix the broker configuration at `/app/kafka/config/kraft/server.properties` and start the broker in KRaft combined mode (single-node, acting as both broker and controller).

## 2. Topics
Create the following topics on the running broker:

### user-events
- Partitions: 6
- Retention: 7 days
- Max message size: 5 MB (5242880 bytes)

### system-metrics
- Partitions: 3
- Retention: 24 hours
- Cleanup policy: delete

### audit-log
- Partitions: 1
- Cleanup policy: compact
- Minimum cleanable dirty ratio: 0.3

### transactions
- Partitions: 4
- Segment size: 100 MB (104857600 bytes)
- min.insync.replicas: 1

## 3. Producer Configurations

### `/app/configs/safe-producer.properties`
Configure for exactly-once delivery semantics. Must include:
- Appropriate acknowledgment setting for no data loss
- Idempotent producer enabled
- Appropriate retry configuration
- Max in-flight requests per connection set for ordering guarantee with idempotence

### `/app/configs/throughput-producer.properties`
Configure for maximum throughput. Must include:
- Snappy compression
- Appropriate linger time for batching (at least 5ms)
- Batch size of at least 32 KB

## 4. Consumer Configuration

### `/app/configs/reliable-consumer.properties`
Configure for at-least-once delivery semantics with manual offset management:
- Disable automatic offset commit
- Set offset reset policy to read from earliest available

## 5. Capacity Planning Questions
Write single-integer answers to the following files:

### `/app/answers/q1.txt`
A Kafka topic has replication.factor=3, acks=all, and min.insync.replicas=2. What is the maximum number of broker failures that can be tolerated while writes still succeed?

### `/app/answers/q2.txt`
A producer writes data at 1 GB/sec. Each consumer instance can process data at 250 MB/sec. What is the minimum number of partitions needed for consumers to keep up with the producer?

### `/app/answers/q3.txt`
A ZooKeeper ensemble must tolerate the loss of 3 servers. Using the formula 2n+1, what is the minimum number of ZooKeeper servers required?

### `/app/answers/q4.txt`
A topic has 10 partitions. A consumer group has 15 consumers. How many consumers will be idle?

### `/app/answers/q5.txt`
A Kafka topic has replication.factor=3, acks=all, and min.insync.replicas=1. What is the maximum number of broker failures that can be tolerated while writes still succeed?

## 6. Verification
Produce at least 10 messages to the `user-events` topic and consume them back:
- Save produced messages to `/app/verification/produced.txt` (one per line)
- Save consumed messages to `/app/verification/consumed.txt` (one per line)
