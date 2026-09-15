An Ansible project in `/app/` generates nginx configuration files for a three-tier web infrastructure with hosts `web1` (frontend), `api1` (backend API proxy), and `mon1` (monitoring dashboard). Running `ansible-playbook playbook.yml` from `/app/` should produce host-specific configuration files under `/tmp/nginx_configs/<hostname>/`.

The project is currently broken. Some defects cause the playbook to abort with errors; others allow execution to complete but silently produce incorrect configuration output. The issues are spread across the inventory, roles, and templates.

Complete all three objectives:

**Objective 1 — Fix all defects** so the playbook runs to completion and the generated nginx configurations correctly reflect the intended architecture:

- **Frontend (`web1`)**: `worker_connections 2048`, SSL enabled (`listen 443 ssl`) with `ssl_certificate` and `ssl_certificate_key` directives, `server_tokens off`, `gzip on`, rate limiting via `limit_req_zone`, both base HTTP tuning parameters (`sendfile on`, `tcp_nopush on`) and SSL-specific parameters (`ssl_protocols TLSv1.2 TLSv1.3`, `ssl_ciphers HIGH:!aNULL:!MD5`).
- **Backend (`api1`)**: `worker_connections 1024`, `server_tokens off`, `gzip on`, properly formed `upstream` blocks (including `app_cluster` with weighted server members), no rate limiting, no SSL.
- **Monitoring (`mon1`)**: `worker_connections 256`, `server_tokens on` (role default), no gzip, no rate limiting, `proxy_pass http://127.0.0.1:3000`.

**Objective 2 — Design and implement a fourth tier: caching reverse proxy.** Add a new `cache1` host that serves as a caching proxy in front of origin servers. You must decide where to place the new group in the inventory hierarchy and how to structure its variables so the tier integrates correctly without reintroducing any of the anti-patterns you found in Objective 1. The caching tier must produce correct configs with:

- `worker_connections 4096`
- Inheritance of `server_tokens off` and `gzip on` from the webservers group
- SSL on port 443 with certificate `/etc/ssl/certs/cache.pem` and key `/etc/ssl/private/cache.key`
- A `proxy_cache_path` directive in the main config (the template must be extended to support this)
- An `origin_servers` upstream block using `least_conn` balancing with members `10.0.1.10:8080` and `10.0.1.11:8080`
- `proxy_pass http://origin_servers` in the site configuration
- Base HTTP params (`sendfile on`, `tcp_nopush on`) and SSL params (`ssl_protocols TLSv1.2 TLSv1.3`, `ssl_ciphers HIGH:!aNULL:!MD5`) without parameter dictionary replacement
- No rate limiting

**Objective 3 — Produce an architecture evaluation** at `/app/architecture_review.json`. This JSON object must contain three sections:

- `"bugs"`: array of at least 6 entries documenting each defect. Each entry requires `"file"` (relative to `/app/`), `"severity"` (`"critical"` if it halts execution, `"major"` if it silently corrupts output), `"description"`, and `"fix"`. Must include both severity levels.
- `"anti_patterns"`: array of at least 4 entries. Each must have `"pattern_name"` (a named anti-pattern you identified), `"description"` (how this pattern manifests), and `"prevention_principle"` (a reusable design principle that prevents this class of bug in future Ansible projects).
- `"cache_tier_rationale"`: object with keys `"group_placement"`, `"ssl_implementation"`, and `"variable_strategy"`, each explaining the design decision you made for the cache tier and why it avoids the anti-patterns discovered in Objective 1.

Verify by running `ansible-playbook playbook.yml` from `/app/` and inspecting all four host directories under `/tmp/nginx_configs/`.