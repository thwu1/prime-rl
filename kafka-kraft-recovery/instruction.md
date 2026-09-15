A Kafka 3.6.1 KRaft installation at `/app/kafka/` is being prepared for a multi-tenant microservices platform. The broker configuration at `/app/kafka/config/kraft/server.properties` contains multiple interrelated errors preventing startup.

The platform's workload specifications and cluster evolution requirements are at `/app/workloads.md`. Configuration change proposals requiring expert assessment are at `/app/config_proposals.md`.

Deliver:

- Running Kafka broker in KRaft combined mode on port 9092
- Topics configured per workload SLAs — partition counts derived from throughput ratios, retention policies, cleanup strategies (evaluating when combined policies are needed), segment sizes, and message size limits
- Client configuration profiles at `/app/configs/` implementing exactly-once, throughput-optimized, and transactional consumption semantics
- Partition reassignment plan at `/app/evaluation/reassignment.json` — design a rack-aware, balanced migration plan for expanding a topic from 3 to 5 brokers satisfying all constraints specified in `/app/workloads.md`
- Configuration governance verdicts at `/app/evaluation/config_audit.json` — evaluate each proposal in `/app/config_proposals.md` and render ACCEPT or REJECT verdicts with justification
- Cluster verification artifacts at `/app/verification/`