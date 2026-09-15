A microservices API platform is completely offline due to a cascading failure. The **service-control** component — which enforces quota and policy checks on every API request — is crash-looping across all three regional instances. The **API gateway** cannot reach any healthy service-control instance and returns 503 to all clients.

The system is at `/app/`:

- `/app/service_control/` — Policy/quota enforcement service (Flask, 3 instances on ports 5001–5003)
- `/app/gateway/` — API gateway (Flask, port 5000)
- `/app/config/flags.yaml` — Feature flag configuration
- `/app/data/policies_region{1,2,3}.db` — Regional SQLite policy databases
- `/app/scripts/` — Startup, health check, and database setup utilities
- `/app/supervisord.conf` — Process supervisor configuration
- `/app/logs/` — Crash logs from the failure

A configuration change was pushed to the policy databases at approximately 10:45 and replicated to all three regions within seconds. Service-control instances began crash-looping immediately afterward.

Diagnose the complete failure chain, fix all underlying issues, and restore the system to full health. The remediated system must be resilient to this class of failure — all three service-control instances and the gateway must pass health checks.