#!/usr/bin/env python3
"""Diagnose and repair all broken infrastructure configurations."""

import os

# ============================================================
# 1. BIND9 named.conf — fix view ordering, TSIG, zone scoping
# ============================================================

named_conf = """\
// BIND9 Split-Horizon DNS Configuration for infra.example.com

acl "trusted" {
    10.20.30.0/24;
    localhost;
    localnets;
};

key "xfer-key" {
    algorithm hmac-sha256;
    secret "R3BpK3FmYWN0b3J5MTIzNDU2Nzg5MGFiY2RlZg==";
};

options {
    directory "/var/cache/bind";
    listen-on { any; };
    listen-on-v6 { none; };
    allow-query { any; };
    forwarders {
        8.8.8.8;
        8.8.4.4;
    };
    dnssec-validation auto;
};

view "internal" {
    match-clients { trusted; };
    recursion yes;

    zone "infra.example.com" {
        type master;
        file "/app/dns/zones/db.infra.example.com.internal";
        allow-transfer { key "xfer-key"; };
        also-notify { 10.20.30.3; };
    };

    zone "30.20.10.in-addr.arpa" {
        type master;
        file "/app/dns/zones/db.10.20.30";
        allow-transfer { key "xfer-key"; };
    };
};

view "external" {
    match-clients { any; };
    recursion no;

    zone "infra.example.com" {
        type master;
        file "/app/dns/zones/db.infra.example.com.external";
        allow-transfer { none; };
    };
};
"""

with open("/app/dns/named.conf", "w") as f:
    f.write(named_conf)
print("[OK] /app/dns/named.conf")

# ============================================================
# 2. Internal forward zone — create with correct internal IPs
# ============================================================

internal_zone = """\
$TTL 86400
@   IN  SOA ns1.infra.example.com. admin.infra.example.com. (
            2024010101  ; serial
            3600        ; refresh
            900         ; retry
            604800      ; expire
            86400       ; minimum TTL
)

; Nameservers
        IN  NS  ns1.infra.example.com.
        IN  NS  ns2.infra.example.com.

; Mail
        IN  MX  10 mail.infra.example.com.

; Zone apex -> load balancer (A record, not CNAME per RFC 1034)
@       IN  A   10.20.30.1

; Host A records (internal IPs)
lb      IN  A   10.20.30.1
ns1     IN  A   10.20.30.2
ns2     IN  A   10.20.30.3
web1    IN  A   10.20.30.10
web2    IN  A   10.20.30.11
web3    IN  A   10.20.30.12
api1    IN  A   10.20.30.15
api2    IN  A   10.20.30.16
db1     IN  A   10.20.30.20
mail    IN  A   10.20.30.25

; SRV record for HTTP service
_http._tcp  IN  SRV 10 60 80 lb.infra.example.com.
"""

os.makedirs("/app/dns/zones", exist_ok=True)
with open("/app/dns/zones/db.infra.example.com.internal", "w") as f:
    f.write(internal_zone)
print("[OK] /app/dns/zones/db.infra.example.com.internal")

# ============================================================
# 3. External forward zone — create with NAT/VIP IPs
# ============================================================

external_zone = """\
$TTL 86400
@   IN  SOA ns1.infra.example.com. admin.infra.example.com. (
            2024010101  ; serial
            3600        ; refresh
            900         ; retry
            604800      ; expire
            86400       ; minimum TTL
)

; Nameservers
        IN  NS  ns1.infra.example.com.
        IN  NS  ns2.infra.example.com.

; Mail
        IN  MX  10 mail.infra.example.com.

; Zone apex -> load balancer public IP (A record, not CNAME)
@       IN  A   203.0.113.1

; Host A records (external/NAT IPs)
lb      IN  A   203.0.113.1
ns1     IN  A   203.0.113.2
ns2     IN  A   203.0.113.3
web1    IN  A   203.0.113.10
web2    IN  A   203.0.113.10
web3    IN  A   203.0.113.10
api1    IN  A   203.0.113.15
api2    IN  A   203.0.113.15
mail    IN  A   203.0.113.25

; SRV record for HTTP service
_http._tcp  IN  SRV 10 60 80 lb.infra.example.com.
"""

with open("/app/dns/zones/db.infra.example.com.external", "w") as f:
    f.write(external_zone)
print("[OK] /app/dns/zones/db.infra.example.com.external")

# ============================================================
# 4. Reverse zone — fix PTR records (add missing, fix names/dots)
# ============================================================

reverse_zone = """\
$TTL 86400
@   IN  SOA ns1.infra.example.com. admin.infra.example.com. (
            2024010101  ; serial
            3600        ; refresh
            900         ; retry
            604800      ; expire
            86400       ; minimum TTL
)

        IN  NS  ns1.infra.example.com.
        IN  NS  ns2.infra.example.com.

; PTR records for all internal hosts
1       IN  PTR lb.infra.example.com.
2       IN  PTR ns1.infra.example.com.
3       IN  PTR ns2.infra.example.com.
10      IN  PTR web1.infra.example.com.
11      IN  PTR web2.infra.example.com.
12      IN  PTR web3.infra.example.com.
15      IN  PTR api1.infra.example.com.
16      IN  PTR api2.infra.example.com.
20      IN  PTR db1.infra.example.com.
25      IN  PTR mail.infra.example.com.
"""

with open("/app/dns/zones/db.10.20.30", "w") as f:
    f.write(reverse_zone)
print("[OK] /app/dns/zones/db.10.20.30")

# ============================================================
# 5. HAProxy — fix ACL ordering, backend refs, exemptions
# ============================================================

haproxy_cfg = """\
global
    log /dev/log local0
    maxconn 4096
    stats socket /run/haproxy/admin.sock mode 660 level admin

defaults
    mode http
    log global
    option httplog
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend http_front
    bind *:80

    # --- Rate limiting via stick-table ---
    stick-table type ip size 100k expire 10s store http_req_rate(10s)
    http-request track-sc0 src
    acl rate_exceeded sc_http_req_rate(0) gt 20
    acl is_internal src 10.20.30.0/24
    http-request deny deny_status 429 if rate_exceeded !is_internal

    # --- Admin restriction (internal only) ---
    acl is_admin_path path_beg /admin
    http-request deny deny_status 403 if is_admin_path !is_internal
    use_backend admin_servers if is_admin_path

    # --- API version routing ---
    acl is_api_path path_beg /api
    acl is_api_v2 hdr(X-API-Version) -i v2
    use_backend api_v2_servers if is_api_path is_api_v2
    use_backend api_v1_servers if is_api_path

    # --- Static content ---
    acl is_static path_beg /static /assets /images
    use_backend static_servers if is_static

    # --- Default ---
    default_backend web_servers

backend web_servers
    balance roundrobin
    server web1 10.20.30.10:8080 check
    server web2 10.20.30.11:8080 check
    server web3 10.20.30.12:8080 check

backend api_v1_servers
    balance roundrobin
    server api1 10.20.30.15:8081 check
    server api2 10.20.30.16:8081 check

backend api_v2_servers
    balance leastconn
    server api1 10.20.30.15:8082 check
    server api2 10.20.30.16:8082 check

backend static_servers
    balance roundrobin
    server web1 10.20.30.10:8090 check
    server web2 10.20.30.11:8090 check

backend admin_servers
    balance roundrobin
    server web1 10.20.30.10:9090 check
"""

with open("/app/haproxy/haproxy.cfg", "w") as f:
    f.write(haproxy_cfg)
print("[OK] /app/haproxy/haproxy.cfg")

# ============================================================
# 6. MariaDB init.sql — fix privilege scopes
# ============================================================

init_sql = """\
-- MariaDB Initialization for infra.example.com

CREATE DATABASE IF NOT EXISTS appdb;
CREATE DATABASE IF NOT EXISTS appdb_staging;
CREATE DATABASE IF NOT EXISTS appdb_analytics;

USE appdb;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, email) VALUES ('admin', 'admin@infra.example.com');
INSERT INTO orders (user_id, amount, status) VALUES (1, 99.99, 'completed');

-- Application user: CRUD on appdb only
CREATE USER IF NOT EXISTS 'appuser'@'10.20.30.%' IDENTIFIED BY 'SecurePass123!';
GRANT SELECT, INSERT, UPDATE, DELETE ON appdb.* TO 'appuser'@'10.20.30.%';

-- Reporter: read-only on appdb and appdb_analytics
CREATE USER IF NOT EXISTS 'reporter'@'10.20.30.%' IDENTIFIED BY 'SecurePass123!';
GRANT SELECT ON appdb.* TO 'reporter'@'10.20.30.%';
GRANT SELECT ON appdb_analytics.* TO 'reporter'@'10.20.30.%';

-- Migrator: DDL only on appdb (schema changes, no data access)
CREATE USER IF NOT EXISTS 'migrator'@'localhost' IDENTIFIED BY 'SecurePass123!';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES ON appdb.* TO 'migrator'@'localhost';

-- Staging admin: full access to staging only
CREATE USER IF NOT EXISTS 'staging_admin'@'localhost' IDENTIFIED BY 'SecurePass123!';
GRANT ALL PRIVILEGES ON appdb_staging.* TO 'staging_admin'@'localhost';

FLUSH PRIVILEGES;
"""

with open("/app/db/init.sql", "w") as f:
    f.write(init_sql)
print("[OK] /app/db/init.sql")

# ============================================================
# 7. Ansible playbook — fix become, handler-notify consistency
# ============================================================

playbook = """\
---
- name: Deploy infrastructure services
  hosts: infrastructure
  become: true

  tasks:
    - name: Install required packages
      ansible.builtin.apt:
        name:
          - bind9
          - haproxy
          - mariadb-server
        state: present
        update_cache: true

    - name: Deploy BIND9 configuration
      ansible.builtin.copy:
        src: /app/dns/named.conf
        dest: /etc/bind/named.conf
        owner: bind
        group: bind
        mode: "0644"
      notify: restart bind9

    - name: Deploy internal forward zone
      ansible.builtin.copy:
        src: /app/dns/zones/db.infra.example.com.internal
        dest: /var/cache/bind/db.infra.example.com.internal
        owner: bind
        group: bind
        mode: "0644"
      notify: restart bind9

    - name: Deploy external forward zone
      ansible.builtin.copy:
        src: /app/dns/zones/db.infra.example.com.external
        dest: /var/cache/bind/db.infra.example.com.external
        owner: bind
        group: bind
        mode: "0644"
      notify: restart bind9

    - name: Deploy reverse zone
      ansible.builtin.copy:
        src: /app/dns/zones/db.10.20.30
        dest: /var/cache/bind/db.10.20.30
        owner: bind
        group: bind
        mode: "0644"
      notify: restart bind9

    - name: Deploy HAProxy configuration
      ansible.builtin.copy:
        src: /app/haproxy/haproxy.cfg
        dest: /etc/haproxy/haproxy.cfg
        owner: root
        group: root
        mode: "0644"
      notify: restart haproxy

    - name: Deploy MariaDB initialization script
      ansible.builtin.copy:
        src: /app/db/init.sql
        dest: /tmp/init.sql
        mode: "0644"

    - name: Enable and start BIND9
      ansible.builtin.systemd:
        name: named
        enabled: true
        state: started

    - name: Enable and start HAProxy
      ansible.builtin.systemd:
        name: haproxy
        enabled: true
        state: started

    - name: Enable and start MariaDB
      ansible.builtin.systemd:
        name: mariadb
        enabled: true
        state: started

  handlers:
    - name: restart bind9
      ansible.builtin.systemd:
        name: named
        state: restarted

    - name: restart haproxy
      ansible.builtin.systemd:
        name: haproxy
        state: restarted

    - name: restart mariadb
      ansible.builtin.systemd:
        name: mariadb
        state: restarted
"""

with open("/app/ansible/playbook.yml", "w") as f:
    f.write(playbook)
print("[OK] /app/ansible/playbook.yml")

print("\\nAll infrastructure configurations repaired successfully.")
