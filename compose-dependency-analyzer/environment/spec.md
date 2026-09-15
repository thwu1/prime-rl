# Docker Compose Dependency Analyzer — Output Specification

## Overview

Implement a Python tool at `/app/analyzer.py` that reads a Docker Compose YAML file and produces a JSON dependency/conflict analysis report on stdout.

## Usage

```
python3 /app/analyzer.py <path-to-docker-compose.yaml>
```

## Analysis Requirements

### 1. Service Enumeration
List all services defined in the compose file, sorted alphabetically.

### 2. Explicit Dependencies
Extract dependencies declared via `depends_on`. Handle both list format (`depends_on: [a, b]`) and dictionary format (`depends_on: {a: {condition: service_healthy}}`).

### 3. Implicit Dependencies
Detect dependencies implied by environment variable values that reference other services via URL. A value is a URL if it matches the pattern `scheme://...` (any scheme like `http`, `https`, `postgresql`, `redis`, `amqp`, etc.). Extract the hostname from each URL using standard URL parsing. A hostname is an internal service reference if:
- It exactly matches a service name defined in the compose file
- It is not the service itself (no self-references)
- Hostnames containing dots (e.g., `api.stripe.com`) are treated as external and excluded from both implicit dependencies and nonexistent references

### 4. Combined Dependencies
The set union of explicit and implicit dependencies for each service.

### 5. Port Conflicts
Identify groups of two or more services that map to the same host port. Port mappings are in `"host:container"` format; extract the host port (the part before the first colon).

### 6. Volume Conflicts
Identify groups of two or more services that mount the same named volume. Named volumes are volume entries that do not start with `.` or `/` (those are bind mounts). Only check the volume name (part before the first `:`), not the mount path.

### 7. Non-existent Service References
Identify environment variable URL references where the extracted hostname does not match any defined service AND does not contain dots. Report the source service, the referenced hostname, and the environment variable name.

### 8. Circular Dependencies
Using the **combined** dependency graph (explicit + implicit), find all strongly connected components (SCCs) of size > 1. Each SCC is reported as an alphabetically sorted list of service names.

### 9. Startup Waves
Using **only explicit** dependencies (from `depends_on`), compute the parallel startup schedule via topological sort. Each wave contains services whose all explicit dependencies appear in earlier waves. Wave 0 contains services with no explicit dependencies. Services within each wave are sorted alphabetically.

### 10. Critical Path
Compute the longest path through the **explicit** dependency DAG (measured in number of nodes). Report the length and one valid path. A valid path means each consecutive pair `(path[i-1], path[i])` satisfies: `path[i-1]` is in the explicit dependencies of `path[i]`.

### 11. Single Points of Failure
For each service, compute how many other services are transitively affected if it fails, using the **explicit** dependency graph. A service B is affected by the failure of A if B directly or transitively depends on A (via `depends_on` chains). Sort by affected count descending, then by service name ascending.

## Output JSON Format

```json
{
  "services": ["alphabetically sorted list of all service names"],
  "explicit_dependencies": {
    "service-name": ["sorted list of depends_on targets"],
    ...
  },
  "implicit_dependencies": {
    "service-name": ["sorted list of env-var-detected service refs"],
    ...
  },
  "combined_dependencies": {
    "service-name": ["sorted union of explicit and implicit"],
    ...
  },
  "port_conflicts": [
    {"host_port": 8080, "services": ["sorted service names"]}
  ],
  "volume_conflicts": [
    {"volume": "volume_name", "services": ["sorted service names"]}
  ],
  "nonexistent_references": [
    {
      "service": "source-service",
      "referenced_service": "undefined-hostname",
      "env_var": "ENV_VAR_NAME"
    }
  ],
  "circular_dependencies": [
    ["sorted", "scc", "members"]
  ],
  "startup_waves": [
    ["wave-0-services-sorted"],
    ["wave-1-services-sorted"],
    ...
  ],
  "critical_path_length": 4,
  "critical_path": ["start-node", "...", "end-node"],
  "single_points_of_failure": [
    {
      "service": "name",
      "affected_count": 6,
      "affected_services": ["sorted affected service names"]
    }
  ]
}
```

All lists of service names must be sorted alphabetically for deterministic output. The `nonexistent_references` list should be sorted by `(service, env_var)`. The `port_conflicts` and `volume_conflicts` lists should be sorted by port/volume name. Each service must appear as a key in all three dependency maps, even if its dependency list is empty.
