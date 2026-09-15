An event-driven order processing system backed by Apache Kafka is deployed at `/app/`. It processes e-commerce order commands, produces domain events, orchestrates fulfillment workflows, and relays events via a transactional outbox. The codebase has bugs across multiple components -- topic configuration, command processing, saga orchestration, and outbox delivery -- causing integration test failures.

Kafka 3.7.0 (KRaft mode, single-node) is pre-installed at `/opt/kafka` and can be started via `/usr/local/bin/start-kafka.sh`.

Diagnose and fix all issues in `/app/`. The correctly working system must:

- Consume commands from `order-commands` and produce domain events keyed by their aggregate identifier with accurate computed totals
- Guarantee exactly-once processing via idempotent production and persistent deduplication
- Route unparseable or invalid input to a dead-letter topic
- Maintain per-customer state on a compacted topic
- Orchestrate multi-step fulfillment with correct compensation semantics on failure, persisting full saga state to SQLite
- Relay outbox events to their destination topics, tracking publication status and timestamps
- Provision Kafka topics with cleanup policies, partition counts, and retention appropriate for each topic's data lifecycle