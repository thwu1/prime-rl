#!/usr/bin/env python3
"""
Solve the multi-service infrastructure configuration repair task.

Fixes all broken configurations and creates missing files:
- DNS: named.conf, forward zone, reverse zone, IPv6 reverse zone
- HAProxy: haproxy.cfg
- Apache: virtual hosts and ports.conf
- MariaDB: setup.sql
- Ansible: deploy.yml

"""

import os
import yaml


def ensure_dirs():
    """Create all required directories."""
    dirs = [
        "/app/services/dns/zones",
        "/app/services/haproxy",
        "/app/services/apache/sites-available",
        "/app/services/mariadb",
        "/app/services/ansible",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def fix_named_conf():
    """Fix named.conf: add missing semicolon, correct zone file path, add IPv6 zone."""
    content = """\
options {
    directory "/var/cache/bind";

    forwarders {
        8.8.8.8;
        8.8.4.4;
    };

    dnssec-validation auto;
    listen-on { any; };
    listen-on-v6 { any; };
    allow-query { any; };
    recursion yes;
};

zone "infra.example.com" IN {
    type master;
    file "/app/services/dns/zones/infra.example.com.zone";
    allow-transfer { 10.0.1.2; };
};

zone "1.0.10.in-addr.arpa" IN {
    type master;
    file "/app/services/dns/zones/1.0.10.in-addr.arpa.zone";
    allow-transfer { 10.0.1.2; };
};

zone "1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa" IN {
    type master;
    file "/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone";
    allow-transfer { 10.0.1.2; };
};
"""
    with open("/app/services/dns/named.conf", "w") as f:
        f.write(content)


def fix_forward_zone():
    """Fix forward zone: remove CNAME at apex, fix MX-to-CNAME, add trailing dots."""
    content = """\
$TTL 86400
$ORIGIN infra.example.com.
@   IN  SOA  ns1.infra.example.com.  admin.infra.example.com. (
            2024010100  ; serial
            3600        ; refresh
            1800        ; retry
            604800      ; expire
            86400       ; minimum
        )

; Nameservers
        IN  NS   ns1.infra.example.com.
        IN  NS   ns2.infra.example.com.

; Nameserver addresses
ns1     IN  A     10.0.1.1
ns2     IN  A     10.0.1.2
ns1     IN  AAAA  2001:db8:1::1
ns2     IN  AAAA  2001:db8:1::2

; Web tier — apex uses A record instead of CNAME
@       IN  A     10.0.1.10
web1    IN  A     10.0.1.10
web2    IN  A     10.0.1.11
web3    IN  A     10.0.1.12
web1    IN  AAAA  2001:db8:1::10

; Application tier
app     IN  A     10.0.1.20

; Database tier
db      IN  A     10.0.1.30

; Mail — smtp uses A record so MX can point to it (RFC 2181)
mail    IN  A     10.0.1.40
smtp    IN  A     10.0.1.40
@       IN  MX  10  smtp

; Monitoring — CNAME uses relative name to avoid trailing-dot issues
monitor IN  A     10.0.1.50
grafana IN  CNAME  monitor

; Service discovery — SRV targets use trailing dots
_https._tcp  IN  SRV  0 5 443 web1.infra.example.com.
_mysql._tcp  IN  SRV  0 5 3306 db.infra.example.com.

; SPF
@       IN  TXT  "v=spf1 mx ~all"
"""
    with open("/app/services/dns/zones/infra.example.com.zone", "w") as f:
        f.write(content)


def fix_reverse_zone():
    """Fix reverse zone: use relative PTR owners, remove dangling backup PTR."""
    content = """\
$TTL 86400
$ORIGIN 1.0.10.in-addr.arpa.
@   IN  SOA  ns1.infra.example.com.  admin.infra.example.com. (
            2024010100
            3600
            1800
            604800
            86400
        )

        IN  NS   ns1.infra.example.com.
        IN  NS   ns2.infra.example.com.

; PTR records — owners are relative to the zone (last octet only)
1         IN  PTR  ns1.infra.example.com.
2         IN  PTR  ns2.infra.example.com.
10        IN  PTR  web1.infra.example.com.
11        IN  PTR  web2.infra.example.com.
12        IN  PTR  web3.infra.example.com.
20        IN  PTR  app.infra.example.com.
30        IN  PTR  db.infra.example.com.
40        IN  PTR  mail.infra.example.com.
50        IN  PTR  monitor.infra.example.com.
"""
    with open("/app/services/dns/zones/1.0.10.in-addr.arpa.zone", "w") as f:
        f.write(content)


def create_ipv6_reverse_zone():
    """Create IPv6 reverse zone for 2001:db8:1::/48 with nibble-format PTR records."""
    # Zone: 1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa (covers /48)
    # PTR owners are the remaining 80 bits (20 nibbles) in reversed nibble order
    #
    # 2001:0db8:0001:0000:0000:0000:0000:0001 → 1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
    # 2001:0db8:0001:0000:0000:0000:0000:0002 → 2.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
    # 2001:0db8:0001:0000:0000:0000:0000:0010 → 0.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
    content = """\
$TTL 86400
$ORIGIN 1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.
@   IN  SOA  ns1.infra.example.com.  admin.infra.example.com. (
            2024010100
            3600
            1800
            604800
            86400
        )

        IN  NS   ns1.infra.example.com.
        IN  NS   ns2.infra.example.com.

; PTR records — nibble-reversed relative to /48 zone
; 2001:db8:1::1
1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0  IN  PTR  ns1.infra.example.com.
; 2001:db8:1::2
2.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0  IN  PTR  ns2.infra.example.com.
; 2001:db8:1::10
0.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0  IN  PTR  web1.infra.example.com.
"""
    zone_path = "/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone"
    with open(zone_path, "w") as f:
        f.write(content)


def fix_haproxy():
    """Fix HAProxy: correct typo, remove missing backend ref, add health checks."""
    content = """\
global
    log /dev/log local0
    maxconn 4096
    daemon

defaults
    log global
    mode http
    option httplog
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend web_front
    bind *:443 ssl crt /etc/ssl/private/server.pem
    bind *:80
    http-request redirect scheme https unless { ssl_fc }

    acl is_api path_beg /api
    acl is_admin path_beg /admin

    use_backend api_backend if is_api
    use_backend admin_backend if is_admin
    default_backend web_backend

backend web_backend
    balance roundrobin
    option httpchk GET /healthz
    server web1 10.0.1.10:80 check
    server web2 10.0.1.11:80 check
    server web3 10.0.1.12:80 check

backend api_backend
    balance leastconn
    option httpchk GET /api/health
    server app1 10.0.1.20:8080 check

backend admin_backend
    server admin1 10.0.1.50:8443 check ssl verify none
"""
    with open("/app/services/haproxy/haproxy.cfg", "w") as f:
        f.write(content)


def fix_apache_www():
    """Fix www.conf: correct DocumentRot typo."""
    content = """\
<VirtualHost *:80>
    ServerName www.infra.example.com
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
"""
    with open("/app/services/apache/sites-available/www.conf", "w") as f:
        f.write(content)


def fix_apache_api():
    """Fix api.conf: add missing </Directory> closing tag."""
    content = """\
<VirtualHost *:8080>
    ServerName api.infra.example.com
    DocumentRoot /var/www/api

    <Directory /var/www/api>
        Options FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
"""
    with open("/app/services/apache/sites-available/api.conf", "w") as f:
        f.write(content)


def fix_apache_admin():
    """Fix admin.conf: close <Directory opening tag with >."""
    content = """\
<VirtualHost *:8443>
    ServerName admin.infra.example.com
    DocumentRoot /var/www/admin
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/server.crt
    SSLCertificateKeyFile /etc/ssl/private/server.key

    <Directory /var/www/admin>
        Options FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
"""
    with open("/app/services/apache/sites-available/admin.conf", "w") as f:
        f.write(content)


def fix_apache_ports():
    """Fix ports.conf: add missing Listen directives for API and admin ports."""
    content = """\
Listen 80
Listen 8080
Listen 8443
"""
    with open("/app/services/apache/ports.conf", "w") as f:
        f.write(content)


def create_mariadb_sql():
    """Create MariaDB setup SQL with databases, tables, users, and grants."""
    content = """\
-- Create databases
CREATE DATABASE IF NOT EXISTS app_production;
CREATE DATABASE IF NOT EXISTS app_analytics;

-- Create tables in app_production
USE app_production;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(512) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Create tables in app_analytics
USE app_analytics;

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    payload JSON,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create users and grant privileges
CREATE USER IF NOT EXISTS 'app_user'@'10.0.1.%' IDENTIFIED BY 'app_secure_pass_2024';
GRANT SELECT, INSERT, UPDATE, DELETE ON app_production.* TO 'app_user'@'10.0.1.%';

CREATE USER IF NOT EXISTS 'analytics_reader'@'10.0.1.%' IDENTIFIED BY 'analytics_read_pass_2024';
GRANT SELECT ON app_analytics.* TO 'analytics_reader'@'10.0.1.%';

CREATE USER IF NOT EXISTS 'admin_user'@'localhost' IDENTIFIED BY 'admin_secure_pass_2024';
GRANT ALL PRIVILEGES ON *.* TO 'admin_user'@'localhost';

FLUSH PRIVILEGES;
"""
    with open("/app/services/mariadb/setup.sql", "w") as f:
        f.write(content)


def create_ansible_playbook():
    """Create Ansible deployment playbook with variables, tasks, and handlers."""
    playbook = [
        {
            "name": "Deploy infrastructure services",
            "hosts": "infrastructure",
            "become": True,
            "vars": {
                "dns_zone": "infra.example.com",
                "dns_reverse_zone": "1.0.10.in-addr.arpa",
                "dns_ipv6_reverse_zone": "1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa",
                "haproxy_frontend_port": 443,
                "haproxy_http_port": 80,
                "apache_http_port": 80,
                "apache_api_port": 8080,
                "apache_admin_port": 8443,
                "mariadb_app_db": "app_production",
                "mariadb_analytics_db": "app_analytics",
                "ssl_cert_path": "/etc/ssl/certs/server.crt",
                "ssl_key_path": "/etc/ssl/private/server.key",
                "ssl_pem_path": "/etc/ssl/private/server.pem",
            },
            "tasks": [
                # --- DNS (BIND9) ---
                {
                    "name": "Install BIND9 DNS server",
                    "ansible.builtin.package": {
                        "name": "bind9",
                        "state": "present",
                    },
                },
                {
                    "name": "Create DNS zones directory",
                    "ansible.builtin.file": {
                        "path": "/etc/bind/zones",
                        "state": "directory",
                        "owner": "bind",
                        "group": "bind",
                        "mode": "0755",
                    },
                },
                {
                    "name": "Deploy named.conf for {{ dns_zone }}",
                    "ansible.builtin.template": {
                        "src": "templates/named.conf.j2",
                        "dest": "/etc/bind/named.conf",
                        "owner": "bind",
                        "group": "bind",
                        "mode": "0644",
                    },
                    "notify": "restart bind9",
                },
                {
                    "name": "Deploy DNS forward zone",
                    "ansible.builtin.template": {
                        "src": "templates/forward.zone.j2",
                        "dest": "/etc/bind/zones/{{ dns_zone }}.zone",
                        "owner": "bind",
                        "group": "bind",
                        "mode": "0644",
                    },
                    "notify": "restart bind9",
                },
                {
                    "name": "Deploy DNS reverse zone",
                    "ansible.builtin.template": {
                        "src": "templates/reverse.zone.j2",
                        "dest": "/etc/bind/zones/{{ dns_reverse_zone }}.zone",
                        "owner": "bind",
                        "group": "bind",
                        "mode": "0644",
                    },
                    "notify": "restart bind9",
                },
                {
                    "name": "Deploy DNS IPv6 reverse zone",
                    "ansible.builtin.template": {
                        "src": "templates/ipv6-reverse.zone.j2",
                        "dest": "/etc/bind/zones/{{ dns_ipv6_reverse_zone }}.zone",
                        "owner": "bind",
                        "group": "bind",
                        "mode": "0644",
                    },
                    "notify": "restart bind9",
                },
                {
                    "name": "Ensure BIND9 is enabled and started",
                    "ansible.builtin.service": {
                        "name": "bind9",
                        "state": "started",
                        "enabled": True,
                    },
                },
                # --- HAProxy ---
                {
                    "name": "Install HAProxy load balancer",
                    "ansible.builtin.package": {
                        "name": "haproxy",
                        "state": "present",
                    },
                },
                {
                    "name": "Deploy HAProxy configuration",
                    "ansible.builtin.template": {
                        "src": "templates/haproxy.cfg.j2",
                        "dest": "/etc/haproxy/haproxy.cfg",
                        "mode": "0644",
                    },
                    "notify": "restart haproxy",
                },
                {
                    "name": "Ensure HAProxy is enabled and started",
                    "ansible.builtin.service": {
                        "name": "haproxy",
                        "state": "started",
                        "enabled": True,
                    },
                },
                # --- Apache ---
                {
                    "name": "Install Apache2 HTTP server",
                    "ansible.builtin.package": {
                        "name": "apache2",
                        "state": "present",
                    },
                },
                {
                    "name": "Deploy Apache ports configuration",
                    "ansible.builtin.template": {
                        "src": "templates/ports.conf.j2",
                        "dest": "/etc/apache2/ports.conf",
                    },
                    "notify": "restart apache2",
                },
                {
                    "name": "Deploy Apache virtual host configs",
                    "ansible.builtin.template": {
                        "src": "templates/{{ item }}.j2",
                        "dest": "/etc/apache2/sites-available/{{ item }}",
                    },
                    "loop": ["www.conf", "api.conf", "admin.conf"],
                    "notify": "restart apache2",
                },
                {
                    "name": "Enable Apache SSL module for port {{ apache_admin_port }}",
                    "community.general.apache2_module": {
                        "name": "ssl",
                        "state": "present",
                    },
                    "notify": "restart apache2",
                },
                {
                    "name": "Ensure Apache2 is enabled and started",
                    "ansible.builtin.service": {
                        "name": "apache2",
                        "state": "started",
                        "enabled": True,
                    },
                },
                # --- MariaDB ---
                {
                    "name": "Install MariaDB server",
                    "ansible.builtin.package": {
                        "name": "mariadb-server",
                        "state": "present",
                    },
                },
                {
                    "name": "Ensure MariaDB is enabled and started",
                    "ansible.builtin.service": {
                        "name": "mariadb",
                        "state": "started",
                        "enabled": True,
                    },
                },
                {
                    "name": "Create application database {{ mariadb_app_db }}",
                    "community.mysql.mysql_db": {
                        "name": "{{ mariadb_app_db }}",
                        "state": "present",
                    },
                },
                {
                    "name": "Create analytics database {{ mariadb_analytics_db }}",
                    "community.mysql.mysql_db": {
                        "name": "{{ mariadb_analytics_db }}",
                        "state": "present",
                    },
                },
                {
                    "name": "Create application database user",
                    "community.mysql.mysql_user": {
                        "name": "app_user",
                        "host": "10.0.1.%",
                        "priv": "{{ mariadb_app_db }}.*:SELECT,INSERT,UPDATE,DELETE",
                        "state": "present",
                    },
                },
                {
                    "name": "Create analytics reader user",
                    "community.mysql.mysql_user": {
                        "name": "analytics_reader",
                        "host": "10.0.1.%",
                        "priv": "{{ mariadb_analytics_db }}.*:SELECT",
                        "state": "present",
                    },
                },
                {
                    "name": "Create admin database user",
                    "community.mysql.mysql_user": {
                        "name": "admin_user",
                        "host": "localhost",
                        "priv": "*.*:ALL",
                        "state": "present",
                    },
                },
            ],
            "handlers": [
                {
                    "name": "restart bind9",
                    "ansible.builtin.service": {
                        "name": "bind9",
                        "state": "restarted",
                    },
                },
                {
                    "name": "restart haproxy",
                    "ansible.builtin.service": {
                        "name": "haproxy",
                        "state": "restarted",
                    },
                },
                {
                    "name": "restart apache2",
                    "ansible.builtin.service": {
                        "name": "apache2",
                        "state": "restarted",
                    },
                },
            ],
        }
    ]

    with open("/app/services/ansible/deploy.yml", "w") as f:
        yaml.dump(playbook, f, default_flow_style=False, sort_keys=False)


def main():
    ensure_dirs()
    fix_named_conf()
    fix_forward_zone()
    fix_reverse_zone()
    create_ipv6_reverse_zone()
    fix_haproxy()
    fix_apache_www()
    fix_apache_api()
    fix_apache_admin()
    fix_apache_ports()
    create_mariadb_sql()
    create_ansible_playbook()
    print("All configurations fixed and missing files created successfully.")


if __name__ == "__main__":
    main()
