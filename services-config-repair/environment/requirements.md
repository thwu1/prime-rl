# Infrastructure Services Configuration Requirements

## Overview
The `infra.example.com` domain hosts a multi-tier web application with the following infrastructure:
- **Network**: 10.0.1.0/24 (IPv4), 2001:db8:1::/48 (IPv6)
- **Services**: DNS, HAProxy, Apache, MariaDB

## DNS (BIND9)
Configuration at `/app/services/dns/`.

### Requirements
- `named.conf` must pass `named-checkconf` validation
- All zone files must pass `named-checkzone` validation
- Zone records must comply with RFC 1912 (CNAME restrictions) and RFC 2181 (MX requirements)
- Forward and reverse DNS records must be consistent (every PTR target must have a corresponding forward A record)
- All fully qualified domain names in record data must include trailing dots
- PTR record owners in reverse zones must use relative names (last octet only for /24 zones)

### Infrastructure Hosts
| Hostname | IPv4 | IPv6 | Role |
|----------|------|------|------|
| ns1 | 10.0.1.1 | 2001:db8:1::1 | Primary nameserver |
| ns2 | 10.0.1.2 | 2001:db8:1::2 | Secondary nameserver |
| web1 | 10.0.1.10 | 2001:db8:1::10 | Web server 1 |
| web2 | 10.0.1.11 | — | Web server 2 |
| web3 | 10.0.1.12 | — | Web server 3 |
| app | 10.0.1.20 | — | Application server |
| db | 10.0.1.30 | — | Database server |
| mail/smtp | 10.0.1.40 | — | Mail server |
| monitor | 10.0.1.50 | — | Monitoring server |

### Zone Apex
The zone apex (`infra.example.com`) should resolve to the primary web server IP (10.0.1.10).

### IPv6 Reverse Zone
Create an IPv6 reverse zone for the `2001:db8:1::/48` prefix at `/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone` with PTR records for all hosts that have AAAA records (ns1, ns2, web1). Add the corresponding zone stanza to `named.conf`.

## HAProxy
Configuration at `/app/services/haproxy/haproxy.cfg`.

### Requirements
- Must pass `haproxy -c -f` validation
- TLS termination on port 443 using `/etc/ssl/private/server.pem`
- HTTP to HTTPS redirect on port 80
- Three backends: web (round-robin), api (least connections), admin
- ACL-based routing: `/api` → api_backend, `/admin` → admin_backend
- Web backend servers must have HTTP health checks enabled

## Apache
Configuration at `/app/services/apache/`.

### Requirements
- All virtual host configs must have valid syntax (properly closed tags, correct directives)
- Three virtual hosts:
  - `www.infra.example.com` on port 80, DocumentRoot `/var/www/html`
  - `api.infra.example.com` on port 8080, DocumentRoot `/var/www/api`
  - `admin.infra.example.com` on port 8443 with SSL, DocumentRoot `/var/www/admin`
- `ports.conf` must include Listen directives for all required ports

## MariaDB
Create `/app/services/mariadb/setup.sql` with the following:

### Databases
- `app_production`
- `app_analytics`

### Tables in `app_production`
- `users` (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255) UNIQUE NOT NULL, email VARCHAR(255) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
- `sessions` (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, token VARCHAR(512) NOT NULL, expires_at TIMESTAMP NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id))

### Tables in `app_analytics`
- `events` (id INT AUTO_INCREMENT PRIMARY KEY, event_type VARCHAR(100) NOT NULL, payload JSON, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)

### Users and Privileges
- `app_user`@`10.0.1.%` — SELECT, INSERT, UPDATE, DELETE on `app_production`
- `analytics_reader`@`10.0.1.%` — SELECT only on `app_analytics`
- `admin_user`@`localhost` — ALL PRIVILEGES on all databases
- End with `FLUSH PRIVILEGES`

## Ansible
Create `/app/services/ansible/deploy.yml` — a deployment playbook that:
- Targets hosts group `infrastructure`
- Defines variables for service-specific settings (zone names, ports, database names, etc.)
- Includes tasks for all four services: DNS (BIND9), HAProxy, Apache, MariaDB
- Uses appropriate Ansible modules (template, service, package, mysql_db, mysql_user, etc.)
- Includes handlers for service restarts (bind9, haproxy, apache2)
- Ensures services are enabled and started
