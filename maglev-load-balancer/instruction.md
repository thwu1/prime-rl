A production L4 load balancer failed during a traffic incident. Forensic evidence and a partial codebase have been recovered. Three deliverables are required to bring the replacement system online.

## Traffic Capture Analysis

A packet capture from the incident is at `/app/captures/incident.pcap`. It contains UDP traffic between clients and four backend servers routed through a VIP at `10.0.0.100`.

Analyze the capture and produce `/app/analysis/traffic_stats.json` with the following fields:

- `total_requests` -- count of UDP packets with destination port 80
- `total_responses` -- count of UDP packets with source port 80
- `backend_distribution` -- JSON object mapping each backend IP to its response count
- `most_loaded_backend` -- the backend IP that handled the most responses
- `unique_client_ips` -- count of distinct client source IPs in request packets

An incident summary describing the observed symptoms is at `/app/incident.md`.

## Proxy Configuration

The nginx configuration at `/app/nginx/nginx.conf` needs to be corrected. It must proxy TCP connections to four backend servers at `127.0.0.1:8001` through `127.0.0.1:8004`. The upstream block must be named `backends` and must use a hashing strategy that minimizes connection redistribution when individual backend servers are added or removed. Validate your configuration with `nginx -t -c /app/nginx/nginx.conf`.

## Load Balancer Module

Implement a `LoadBalancer` class in `/app/balancer.py` that extends `LoadBalancerBase` from `/app/framework.py`. Study the framework's hash utilities, their signatures, and the abstract interface carefully before implementing.

The module must satisfy all of the following simultaneously:

- The lookup table contains exactly `TABLE_SIZE` entries, each mapping to a healthy backend ID
- For equal-weight backends, each backend's share of the table deviates less than 2% from the ideal `1/N` share
- For weighted backends, shares are proportional to weights (e.g., weight-3 gets roughly 3x the entries of weight-1)
- Removing one of N equal-weight backends changes fewer than `TABLE_SIZE * 1.5 / N` table entries
- The table is deterministic: identical regardless of the order backends were added
- Connection tracking: existing flows are preserved when a backend becomes unhealthy; new connections are never assigned to unhealthy backends; FIN packets tear down tracked connections without creating new entries; flows to entirely-removed backends are remapped on next lookup