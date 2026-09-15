A multi-service API management platform at `/app/` entered a cascading failure state shortly after a routine batch policy synchronization event. The system has three interacting components:

- **Service Control** (`/app/service_control/`): Evaluates API requests against enforcement policies from `/app/db/policies.db`
- **API Gateway** (`/app/gateway/`): Pool of workers that route requests through Service Control for policy checks
- **Policy Replicator** (`/app/replicator/`): Synchronizes policy updates into the active policies database

Crash and connection logs are at `/app/logs/`. Restore the platform to a production-resilient state where:

1. Service Control serves policy-check requests indefinitely without process failures, regardless of what records exist in the database
2. Gateway workers recover from upstream outages in a manner that is safe for the broader system under high concurrency
3. All replicator operations enforce invariants that prevent records capable of destabilizing downstream components from being persisted
4. Existing database contents and schema remain unmodified

All fixes must be applied to the source files under `/app/`.