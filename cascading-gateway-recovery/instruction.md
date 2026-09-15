A multi-component API gateway system at `/app/` is experiencing a cascading failure. The architecture consists of three HTTP gateway worker processes behind an HAProxy load balancer, managed by supervisord. A SQLite database at `/app/data/config.db` stores quota policy configurations that workers enforce on incoming API requests.

The system is currently down. Two of the three workers are in a crash loop and never start serving. The third worker was patched by a previous incident responder and appears to be running, but client reports indicate that API responses from it are malformed or empty. The health monitoring system (`/app/services/monitor.py --check`) reports the system as healthy, but this does not match observed behavior. Incident timeline logs are in `/app/logs/`. Service source code is in `/app/services/`. Process and load balancer configurations are in `/app/config/`.

Diagnose the root cause of the cascading failure, evaluate the previous responder's mitigation, and restore the system to full operational health. When the task is complete:

- All three gateway workers must be running and serving valid, non-empty JSON API responses (with `"status": "ok"`) through the HAProxy load balancer on port 80
- The load balancer must distribute traffic across all healthy workers
- Health monitoring must report accurate, real-time system state
- The configuration management tool (`/app/services/config_pusher.py`) must reject the class of invalid policy data that triggered this incident
- Workers must handle degraded or malformed policy data gracefully without crashing
- Database reconnection logic must not cause resource exhaustion under concurrent failure scenarios