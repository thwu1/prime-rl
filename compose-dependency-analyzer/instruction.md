A microservices platform at `/app/` uses a multi-file Docker Compose configuration:

- `/app/docker-compose.yml` — base configuration
- `/app/docker-compose.prod.yml` — production overlay
- `/app/.env` — default environment variables
- `/app/.env.prod` — production environment overrides

Build `/app/audit.py` that determines the effective production runtime configuration and produces a comprehensive infrastructure audit report. Execute as: `python3 /app/audit.py`

Output a single JSON object to stdout with the following keys. All lists sorted alphabetically by their primary identifying field; all sub-lists also sorted.

- `services`: all service names in the effective configuration
- `network_violations`: services that reference another defined service via an environment variable URL but cannot actually reach it because the two services share no Docker network — each: `{source, target, env_var, source_networks, target_networks}`
- `port_conflicts`: host ports bound by more than one service — each: `{host_port (int), services}`
- `resource_violations`: services where `deploy.resources.reservations.memory` exceeds `deploy.resources.limits.memory` — each: `{service, limit, reservation}`
- `healthcheck_gaps`: `depends_on` entries with `condition: service_healthy` where the dependency defines no `healthcheck` — each: `{service, depends_on, condition}`
- `undefined_references`: environment variable URLs whose hostname matches no defined service (exclude external hostnames containing dots) — each: `{service, env_var, referenced_hostname}`
- `circular_dependencies`: groups of services (size > 1) that form mutual dependency loops when considering both declared `depends_on` relationships and implicit connections discoverable from environment variable URLs referencing other defined services — each group as a sorted list; groups sorted by first element
- `startup_waves`: ordered groups of services that can start in parallel, where a service may start once all its declared `depends_on` targets have started — each wave is a sorted list
- `critical_path_length`: integer — the maximum number of services in any chain through declared `depends_on`
- `critical_path`: the service sequence forming the longest chain; break ties alphabetically at each step; if multiple endpoints tie for longest, select the alphabetically first
- `single_points_of_failure`: for each service, how many other services would transitively fail to start (through declared `depends_on`) if it became unavailable — each: `{service, affected_count (int), affected_services}`; sorted by descending affected_count then ascending service name; include every service even if affected_count is 0