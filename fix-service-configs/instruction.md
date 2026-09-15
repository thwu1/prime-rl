The directory `/app/` contains a multi-service infrastructure deployment for the `infra.example.com` domain, spanning internal (10.20.30.0/24) and external (203.0.113.0/24) networks. A previous administrator left the configurations in a broken state — some issues cause validator failures, others are architecturally incorrect but syntactically valid, producing silent misbehavior at runtime.

The authoritative design specification is at `/app/requirements.md`. It defines the complete infrastructure including network topology, IP assignments for all hosts, DNS architecture, load balancer routing policy, database access control model, and Ansible automation requirements.

Diagnose all issues across every component and bring the configurations into full compliance with the specification. Note that passing a validator does not guarantee architectural correctness — some bugs are syntactically valid but violate the design's security or routing semantics. When you are done, the following files must exist and be correct:

- `/app/dns/named.conf` — BIND9 main configuration
- `/app/dns/zones/db.infra.example.com.internal` — Internal forward zone
- `/app/dns/zones/db.infra.example.com.external` — External forward zone
- `/app/dns/zones/db.10.20.30` — Reverse zone
- `/app/haproxy/haproxy.cfg` — HAProxy configuration
- `/app/db/init.sql` — MariaDB initialization script
- `/app/ansible/playbook.yml` — Ansible deployment playbook (uses inventory at `/app/ansible/inventory.ini`)

Each configuration must pass its respective validator:
- `named-checkconf /app/dns/named.conf`
- `named-checkzone infra.example.com /app/dns/zones/db.infra.example.com.internal`
- `named-checkzone infra.example.com /app/dns/zones/db.infra.example.com.external`
- `named-checkzone 30.20.10.in-addr.arpa /app/dns/zones/db.10.20.30`
- `haproxy -c -f /app/haproxy/haproxy.cfg`
- `ansible-playbook --syntax-check -i /app/ansible/inventory.ini /app/ansible/playbook.yml`

Beyond validators, configurations are verified for architectural correctness:

**DNS**: Split-horizon view structure and client-matching precedence, TSIG key name and algorithm, per-view recursion policy, reverse zone scoping (which view serves it and which must not), zone transfer authentication method, A/PTR/NS/MX/SRV record completeness with correct IPs per view per the host assignment tables, and RFC compliance (no CNAME at zone apex per RFC 1034, NS/PTR FQDN trailing dots, mail host as A record per RFC 2181).

**HAProxy**: Security-critical ACL evaluation ordering (rate-limit denial must precede access-control denial, which must precede backend routing rules; versioned API routing must precede default API routing), stick-table presence for rate limiting, network-aware rate-limit exemptions, IP-restricted path access control with appropriate HTTP status codes (429 for rate limits, 403 for access denial), header-based and path-based backend selection, all five backend definitions with correct balance algorithms, and use_backend/default_backend reference consistency.

**Database**: Four distinct user privilege profiles enforcing least privilege — including strict separation of DDL and DML capabilities where specified — across the correct database scopes, and privilege flush.

**Ansible**: Play-level privilege escalation via `become`, handler definitions, and exact handler-name-to-notify-reference consistency.