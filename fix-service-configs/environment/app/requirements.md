# Infrastructure Design Specification — infra.example.com

## Network Topology

| Network   | CIDR              | Purpose                |
|-----------|-------------------|------------------------|
| Internal  | 10.20.30.0/24     | Private infrastructure |
| External  | 203.0.113.0/24    | Public-facing NAT      |

## Host Assignments

### Internal IPs

| Host | IP           | Role            |
|------|--------------|-----------------|
| lb   | 10.20.30.1   | Load balancer   |
| ns1  | 10.20.30.2   | Primary DNS     |
| ns2  | 10.20.30.3   | Secondary DNS   |
| web1 | 10.20.30.10  | Web server      |
| web2 | 10.20.30.11  | Web server      |
| web3 | 10.20.30.12  | Web server      |
| api1 | 10.20.30.15  | API server      |
| api2 | 10.20.30.16  | API server      |
| db1  | 10.20.30.20  | Database        |
| mail | 10.20.30.25  | Mail server     |

### External (NAT) IPs

| Host      | IP            | Notes                     |
|-----------|---------------|---------------------------|
| lb        | 203.0.113.1   | Load balancer public IP   |
| ns1       | 203.0.113.2   | DNS public IP             |
| ns2       | 203.0.113.3   | DNS public IP             |
| web (VIP) | 203.0.113.10  | Shared VIP for web1-3     |
| api (VIP) | 203.0.113.15  | Shared VIP for api1-2     |
| mail      | 203.0.113.25  | Mail public IP            |

In the external view, web1/web2/web3 all resolve to the web VIP (203.0.113.10) and api1/api2 both resolve to the api VIP (203.0.113.15). db1 has no external record.

## File Paths

| File | Path |
|------|------|
| BIND9 config       | `/app/dns/named.conf` |
| Internal fwd zone  | `/app/dns/zones/db.infra.example.com.internal` |
| External fwd zone  | `/app/dns/zones/db.infra.example.com.external` |
| Reverse zone       | `/app/dns/zones/db.10.20.30` |
| HAProxy config     | `/app/haproxy/haproxy.cfg` |
| DB init script     | `/app/db/init.sql` |
| Ansible playbook   | `/app/ansible/playbook.yml` |
| Ansible inventory  | `/app/ansible/inventory.ini` |

---

## 1. DNS — BIND9 Split-Horizon

### ACL

Define an ACL named `trusted` containing `10.20.30.0/24`, `localhost`, and `localnets`.

### TSIG Key

Define a key named `xfer-key` using algorithm `hmac-sha256` with base64 secret `R3BpK3FmYWN0b3J5MTIzNDU2Nzg5MGFiY2RlZg==`. Zone transfers must require this key.

### Options

- `directory "/var/cache/bind"`
- Listen on all IPv4, none IPv6
- Forwarders: 8.8.8.8, 8.8.4.4
- Allow queries from any source

### Views

**View "internal"** (must be defined first in the config):
- `match-clients`: the `trusted` ACL
- Recursion: enabled
- Zones served:
  - `infra.example.com` (forward) — file: `/app/dns/zones/db.infra.example.com.internal`
  - `30.20.10.in-addr.arpa` (reverse) — file: `/app/dns/zones/db.10.20.30`
- Zone transfers: allow with `xfer-key`; also-notify ns2 (10.20.30.3)

**View "external"** (must be defined after internal):
- `match-clients`: `any`
- Recursion: disabled
- Zones served:
  - `infra.example.com` (forward) — file: `/app/dns/zones/db.infra.example.com.external`
- No reverse zone in external view
- Zone transfers: deny (`allow-transfer { none; }`)

### Zone Records — Common Requirements

- SOA: `ns1.infra.example.com. admin.infra.example.com.` serial `2024010101`
- NS records: `ns1.infra.example.com.` and `ns2.infra.example.com.` — trailing dots required on all FQDNs
- MX record: priority 10, target `mail.infra.example.com.` — the mail host must have an A record (not CNAME, per RFC 2181)
- SRV record: `_http._tcp` priority 10, weight 60, port 80, target `lb.infra.example.com.`
- Zone apex (`@`) must have an A record (not CNAME — illegal per RFC 1034) pointing to the lb IP for that view

### Internal Forward Zone

A records using internal IPs for all hosts in the internal table. Zone apex A record points to 10.20.30.1 (lb).

### External Forward Zone

A records using external/NAT IPs per the external table. Zone apex A record points to 203.0.113.1 (lb). No record for db1.

### Reverse Zone (internal view only)

PTR records for every host in the internal IP table. All PTR targets must be FQDNs with trailing dots.

---

## 2. HAProxy — Multi-Tier Routing

### Global

- Log: `/dev/log local0`
- Max connections: 4096
- Stats socket: `/run/haproxy/admin.sock mode 660 level admin`

### Defaults

- Mode: http
- Log: global
- Option: httplog
- Timeouts: connect 5s, client 30s, server 30s

### Frontend `http_front` (bind `*:80`)

Implement ACL-based routing with the following precedence (order is critical):

1. **Rate limiting**: stick-table (type ip, size 100k, expire 10s, store http_req_rate(10s)). Track source IPs. Deny with HTTP 429 if request rate exceeds 20/10s. **Internal network (10.20.30.0/24) is exempt** from rate-limit denial.
2. **Admin restriction**: paths starting with `/admin` are allowed only from the internal network. Deny external clients with HTTP 403. Route allowed admin requests to `admin_servers`.
3. **API version routing**: requests with `X-API-Version` header equal to `v2` on `/api` paths route to `api_v2_servers`.
4. **API default routing**: remaining `/api` paths route to `api_v1_servers`.
5. **Static content**: paths starting with `/static`, `/assets`, or `/images` route to `static_servers`.
6. **Default**: all other traffic to `web_servers`.

### Backends

| Backend         | Balance     | Servers                            | Port | Health |
|-----------------|-------------|------------------------------------|------|--------|
| web_servers     | roundrobin  | web1 (.10), web2 (.11), web3 (.12) | 8080 | check  |
| api_v1_servers  | roundrobin  | api1 (.15), api2 (.16)             | 8081 | check  |
| api_v2_servers  | leastconn   | api1 (.15), api2 (.16)             | 8082 | check  |
| static_servers  | roundrobin  | web1 (.10), web2 (.11)             | 8090 | check  |
| admin_servers   | roundrobin  | web1 (.10)                         | 9090 | check  |

All server IPs use the 10.20.30.x internal addresses.

---

## 3. Database — MariaDB Access Control

### Databases

Create: `appdb`, `appdb_staging`, `appdb_analytics`

### Tables (in `appdb`)

```sql
users(id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(64) NOT NULL, email VARCHAR(128), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
orders(id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, amount DECIMAL(10,2) NOT NULL, status VARCHAR(32) DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

Insert sample data: one user ('admin', 'admin@infra.example.com'), one order (user_id 1, amount 99.99, status 'completed').

### Users and Privileges

All users identified by `'SecurePass123!'`. Apply principle of least privilege:

| User          | Host           | Privileges                              | Scope              |
|---------------|----------------|-----------------------------------------|---------------------|
| appuser       | '10.20.30.%'   | SELECT, INSERT, UPDATE, DELETE          | appdb.*             |
| reporter      | '10.20.30.%'   | SELECT                                  | appdb.* AND appdb_analytics.* |
| migrator      | 'localhost'    | CREATE, ALTER, DROP, INDEX, REFERENCES  | appdb.*             |
| staging_admin | 'localhost'    | ALL PRIVILEGES                          | appdb_staging.*     |

The `migrator` role is for schema migrations only — it must have DDL privileges but explicitly no data manipulation (no SELECT/INSERT/UPDATE/DELETE).

End with `FLUSH PRIVILEGES`.

---

## 4. Ansible Automation

### Playbook Requirements

- Play target: `infrastructure` group (from inventory.ini)
- Privilege escalation: `become: true` at play level
- Tasks: install packages (bind9, haproxy, mariadb-server), deploy configuration files, enable and start services
- Handler names must exactly match their notify references
- Handlers: `restart bind9`, `restart haproxy`, `restart mariadb` — each restarts the corresponding service via systemd
- Jinja2 variable references in values must be properly quoted
