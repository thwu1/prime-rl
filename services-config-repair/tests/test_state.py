"""
Tests for multi-service infrastructure configuration repair and automation.

"""

import os
import re
import subprocess

import pytest
import yaml


# =============================================================================
# DNS Tests
# =============================================================================


class TestDNSNamedConf:
    """Tests for BIND9 named.conf configuration."""

    def test_dns_named_conf_valid(self):
        """named-checkconf must pass on named.conf."""
        result = subprocess.run(
            ["named-checkconf", "/app/services/dns/named.conf"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"named-checkconf failed:\n{result.stderr}"

    def test_named_conf_zone_files_exist(self):
        """All zone files referenced in named.conf must exist on disk."""
        with open("/app/services/dns/named.conf") as f:
            content = f.read()

        files = re.findall(r'file\s+"([^"]+)"', content)
        assert len(files) >= 2, "named.conf should reference at least 2 zone files"
        for filepath in files:
            assert os.path.exists(filepath), (
                f"Zone file referenced in named.conf does not exist: {filepath}"
            )


class TestDNSForwardZone:
    """Tests for the infra.example.com forward zone."""

    def test_dns_forward_zone_valid(self):
        """named-checkzone must pass for the forward zone."""
        result = subprocess.run(
            [
                "named-checkzone",
                "infra.example.com",
                "/app/services/dns/zones/infra.example.com.zone",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"named-checkzone failed:\n{result.stderr}"

    def test_dns_no_cname_at_apex(self):
        """Zone apex (@) must not have CNAME records (RFC 1912 Section 2.4)."""
        with open("/app/services/dns/zones/infra.example.com.zone") as f:
            content = f.read()

        for line in content.split("\n"):
            stripped = line.split(";")[0].strip()
            if not stripped or stripped.startswith("$"):
                continue
            parts = stripped.split()
            if len(parts) >= 3 and parts[0] == "@" and "CNAME" in parts:
                pytest.fail(f"CNAME record found at zone apex: {stripped}")

    def test_dns_mx_not_pointing_to_cname(self):
        """MX targets must not be CNAME aliases (RFC 2181 Section 10.3)."""
        with open("/app/services/dns/zones/infra.example.com.zone") as f:
            content = f.read()

        cname_owners = set()
        mx_targets = []

        for line in content.split("\n"):
            stripped = line.split(";")[0].strip()
            if not stripped or stripped.startswith("$"):
                continue
            parts = stripped.split()
            if "CNAME" in parts:
                idx = parts.index("CNAME")
                if idx >= 1:
                    cname_owners.add(parts[0].lower())
            if "MX" in parts:
                idx = parts.index("MX")
                if idx + 2 < len(parts):
                    mx_targets.append(parts[idx + 2].rstrip(".").lower())

        for target in mx_targets:
            assert target not in cname_owners, (
                f"MX record points to CNAME alias '{target}' — "
                "MX targets must resolve to A/AAAA records directly"
            )

    def test_dns_fqdn_trailing_dots(self):
        """CNAME and SRV targets containing dots must end with a trailing dot."""
        with open("/app/services/dns/zones/infra.example.com.zone") as f:
            content = f.read()

        for line in content.split("\n"):
            stripped = line.split(";")[0].strip()
            if not stripped or stripped.startswith("$"):
                continue
            parts = stripped.split()

            # Check CNAME targets
            if "CNAME" in parts:
                idx = parts.index("CNAME")
                if idx + 1 < len(parts):
                    target = parts[idx + 1]
                    if "." in target and not target.endswith("."):
                        pytest.fail(
                            f"CNAME target '{target}' contains dots but missing "
                            "trailing dot — will be appended to $ORIGIN"
                        )

            # Check SRV targets (priority weight port target)
            if "SRV" in parts:
                idx = parts.index("SRV")
                if idx + 4 <= len(parts):
                    target = parts[idx + 3]
                    if "." in target and not target.endswith("."):
                        pytest.fail(
                            f"SRV target '{target}' contains dots but missing "
                            "trailing dot — will be appended to $ORIGIN"
                        )


class TestDNSReverseZone:
    """Tests for the 1.0.10.in-addr.arpa reverse zone."""

    def test_dns_reverse_zone_valid(self):
        """named-checkzone must pass for the reverse zone."""
        result = subprocess.run(
            [
                "named-checkzone",
                "1.0.10.in-addr.arpa",
                "/app/services/dns/zones/1.0.10.in-addr.arpa.zone",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"named-checkzone failed:\n{result.stderr}"

    def test_dns_reverse_ptr_format(self):
        """PTR owners in a /24 reverse zone must be single octets, not full IPs."""
        with open("/app/services/dns/zones/1.0.10.in-addr.arpa.zone") as f:
            content = f.read()

        for line in content.split("\n"):
            stripped = line.split(";")[0].strip()
            if not stripped or stripped.startswith("$") or stripped.startswith("@"):
                continue
            parts = stripped.split()
            if len(parts) >= 2 and "PTR" in parts:
                owner = parts[0]
                if owner in ("IN", "@"):
                    continue
                assert "." not in owner, (
                    f"PTR owner '{owner}' appears to use a full IP address — "
                    "must use a relative name (single last-octet number)"
                )

    def test_dns_reverse_forward_consistency(self):
        """Every PTR target must have a corresponding forward A record."""
        # Parse forward zone using named-checkzone normalized output
        fwd = subprocess.run(
            [
                "named-checkzone",
                "-o", "-",
                "infra.example.com",
                "/app/services/dns/zones/infra.example.com.zone",
            ],
            capture_output=True,
            text=True,
        )
        assert fwd.returncode == 0, "Forward zone must be valid for consistency check"

        a_names = set()
        for line in fwd.stdout.split("\n"):
            m = re.match(r"^(\S+)\s+\d+\s+IN\s+A\s+", line)
            if m:
                a_names.add(m.group(1).lower())

        # Parse reverse zone
        rev = subprocess.run(
            [
                "named-checkzone",
                "-o", "-",
                "1.0.10.in-addr.arpa",
                "/app/services/dns/zones/1.0.10.in-addr.arpa.zone",
            ],
            capture_output=True,
            text=True,
        )
        assert rev.returncode == 0, "Reverse zone must be valid for consistency check"

        for line in rev.stdout.split("\n"):
            m = re.match(r"^(\S+)\s+\d+\s+IN\s+PTR\s+(\S+)", line)
            if m:
                target = m.group(2).lower()
                assert target in a_names, (
                    f"PTR target '{target}' has no corresponding forward A record"
                )


class TestDNSIPv6ReverseZone:
    """Tests for the IPv6 reverse zone."""

    def test_dns_ipv6_reverse_zone_exists(self):
        """IPv6 reverse zone file must exist."""
        zone_path = (
            "/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone"
        )
        assert os.path.exists(zone_path), (
            "IPv6 reverse zone file not found at expected path"
        )

    def test_dns_ipv6_reverse_zone_valid(self):
        """named-checkzone must pass for the IPv6 reverse zone."""
        result = subprocess.run(
            [
                "named-checkzone",
                "1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa",
                "/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"named-checkzone failed:\n{result.stderr}"

    def test_dns_ipv6_reverse_has_ptrs(self):
        """IPv6 reverse zone must have PTR records for ns1, ns2, and web1."""
        zone_path = (
            "/app/services/dns/zones/1.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.zone"
        )
        with open(zone_path) as f:
            content = f.read()

        assert "ns1.infra.example.com." in content, "Missing PTR for ns1"
        assert "ns2.infra.example.com." in content, "Missing PTR for ns2"
        assert "web1.infra.example.com." in content, "Missing PTR for web1"


# =============================================================================
# HAProxy Tests
# =============================================================================


class TestHAProxy:
    """Tests for HAProxy configuration."""

    def test_haproxy_config_valid(self):
        """haproxy -c must pass."""
        result = subprocess.run(
            ["haproxy", "-c", "-f", "/app/services/haproxy/haproxy.cfg"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"haproxy config check failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_haproxy_has_ssl_frontend(self):
        """Frontend must bind with SSL/TLS for HTTPS termination."""
        with open("/app/services/haproxy/haproxy.cfg") as f:
            content = f.read().lower()
        assert "ssl" in content and "crt" in content, (
            "Frontend missing SSL/TLS binding configuration"
        )

    def test_haproxy_backends_have_health_checks(self):
        """Web backend servers must have HTTP health checks enabled."""
        with open("/app/services/haproxy/haproxy.cfg") as f:
            content = f.read()

        in_web_backend = False
        servers_with_check = 0
        has_httpchk = False

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("backend web_backend"):
                in_web_backend = True
                continue
            if in_web_backend:
                if stripped.startswith("backend ") or stripped.startswith("frontend "):
                    break
                if stripped.startswith("server ") and "check" in stripped:
                    servers_with_check += 1
                if "httpchk" in stripped:
                    has_httpchk = True

        assert servers_with_check >= 2, (
            f"web_backend: only {servers_with_check} server(s) have 'check' enabled"
        )
        assert has_httpchk, "web_backend missing 'option httpchk' for HTTP health checks"


# =============================================================================
# Apache Tests
# =============================================================================


class TestApache:
    """Tests for Apache virtual host configurations."""

    def test_apache_www_conf_valid(self):
        """www.conf must have correct structure and directives."""
        with open("/app/services/apache/sites-available/www.conf") as f:
            content = f.read()
        assert "DocumentRoot" in content, "Missing DocumentRoot directive"
        assert "DocumentRot" not in content, (
            "Typo found: 'DocumentRot' should be 'DocumentRoot'"
        )
        assert "ServerName" in content, "Missing ServerName directive"
        assert content.count("<VirtualHost") == content.count("</VirtualHost>"), (
            "Unclosed VirtualHost tag"
        )
        assert content.count("<Directory") == content.count("</Directory>"), (
            "Unclosed Directory tag"
        )

    def test_apache_api_conf_valid(self):
        """api.conf must have properly closed tags."""
        with open("/app/services/apache/sites-available/api.conf") as f:
            content = f.read()
        assert content.count("<Directory") == content.count("</Directory>"), (
            "Unclosed Directory tag"
        )
        assert "ServerName" in content, "Missing ServerName directive"
        assert content.count("<VirtualHost") == content.count("</VirtualHost>"), (
            "Unclosed VirtualHost tag"
        )

    def test_apache_admin_conf_valid(self):
        """admin.conf must have proper tag syntax and SSL directives."""
        with open("/app/services/apache/sites-available/admin.conf") as f:
            content = f.read()
        assert content.count("<VirtualHost") == content.count("</VirtualHost>"), (
            "Unclosed VirtualHost tag"
        )
        assert content.count("<Directory") == content.count("</Directory>"), (
            "Unclosed Directory tag"
        )
        # Verify all opening tags are properly terminated with >
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("<Directory") and not stripped.startswith("</"):
                assert ">" in stripped, (
                    f"Opening tag not properly closed with '>': {stripped}"
                )
        assert "SSLEngine" in content, "Missing SSLEngine directive for HTTPS vhost"

    def test_apache_ports_conf_complete(self):
        """ports.conf must include Listen directives for all required ports."""
        with open("/app/services/apache/ports.conf") as f:
            content = f.read()
        assert re.search(r"Listen\s+80\b", content), "Missing Listen 80"
        assert "8080" in content, "Missing Listen 8080 for API virtual host"
        assert "8443" in content, "Missing Listen 8443 for admin virtual host"


# =============================================================================
# MariaDB Tests
# =============================================================================


class TestMariaDB:
    """Tests for MariaDB setup SQL."""

    def test_mariadb_setup_sql_exists(self):
        """setup.sql must exist."""
        assert os.path.exists("/app/services/mariadb/setup.sql"), (
            "MariaDB setup.sql not found"
        )

    def test_mariadb_creates_databases(self):
        """SQL must create both required databases."""
        with open("/app/services/mariadb/setup.sql") as f:
            content = f.read().upper()
        assert "CREATE DATABASE" in content or "CREATE SCHEMA" in content, (
            "Missing CREATE DATABASE statement"
        )
        assert "APP_PRODUCTION" in content, "Missing app_production database"
        assert "APP_ANALYTICS" in content, "Missing app_analytics database"

    def test_mariadb_creates_users_and_grants(self):
        """SQL must create users with proper privilege grants."""
        with open("/app/services/mariadb/setup.sql") as f:
            content = f.read()
        content_upper = content.upper()

        assert "APP_USER" in content_upper or "app_user" in content, (
            "Missing app_user"
        )
        assert (
            "ANALYTICS_READER" in content_upper or "analytics_reader" in content
        ), "Missing analytics_reader"
        assert "ADMIN_USER" in content_upper or "admin_user" in content, (
            "Missing admin_user"
        )
        assert "GRANT" in content_upper, "Missing GRANT statements"
        assert "FLUSH PRIVILEGES" in content_upper, "Missing FLUSH PRIVILEGES"

    def test_mariadb_creates_tables(self):
        """SQL must create required tables with proper schema."""
        with open("/app/services/mariadb/setup.sql") as f:
            content = f.read().upper()
        assert "CREATE TABLE" in content, "Missing CREATE TABLE statements"
        assert "USERS" in content, "Missing users table"
        assert "SESSIONS" in content, "Missing sessions table"
        assert "EVENTS" in content, "Missing events table"
        assert "FOREIGN KEY" in content, (
            "Missing FOREIGN KEY constraint on sessions table"
        )


# =============================================================================
# Ansible Tests
# =============================================================================


class TestAnsible:
    """Tests for Ansible deployment playbook."""

    def test_ansible_playbook_exists(self):
        """deploy.yml must exist."""
        assert os.path.exists("/app/services/ansible/deploy.yml"), (
            "Ansible deploy.yml not found"
        )

    def test_ansible_playbook_valid_yaml(self):
        """deploy.yml must be valid YAML with playbook structure."""
        with open("/app/services/ansible/deploy.yml") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, list), "Playbook must be a YAML list of plays"
        assert len(data) > 0, "Playbook is empty"

    def test_ansible_playbook_structure(self):
        """Playbook must have required Ansible play structure."""
        with open("/app/services/ansible/deploy.yml") as f:
            data = yaml.safe_load(f)

        play = data[0]
        assert "hosts" in play, "Play missing 'hosts' field"
        assert "tasks" in play or "roles" in play, (
            "Play missing 'tasks' or 'roles' field"
        )

    def test_ansible_playbook_covers_all_services(self):
        """Playbook must include tasks for DNS, HAProxy, Apache, and MariaDB."""
        with open("/app/services/ansible/deploy.yml") as f:
            content = f.read().lower()

        assert any(kw in content for kw in ("dns", "bind", "named")), (
            "Missing DNS/BIND9 tasks"
        )
        assert "haproxy" in content, "Missing HAProxy tasks"
        assert any(kw in content for kw in ("apache", "httpd", "apache2")), (
            "Missing Apache tasks"
        )
        assert any(kw in content for kw in ("mariadb", "mysql")), (
            "Missing MariaDB tasks"
        )

    def test_ansible_playbook_has_handlers(self):
        """Playbook must include handlers for service restarts."""
        with open("/app/services/ansible/deploy.yml") as f:
            data = yaml.safe_load(f)

        has_handlers = False
        for play in data:
            if "handlers" in play and isinstance(play["handlers"], list):
                if len(play["handlers"]) > 0:
                    has_handlers = True
                    break
        assert has_handlers, "Playbook missing handlers for service restarts"

    def test_ansible_playbook_uses_variables(self):
        """Playbook must define and use variables."""
        with open("/app/services/ansible/deploy.yml") as f:
            content = f.read()

        assert "{{" in content and "}}" in content, (
            "Playbook doesn't use Jinja2 variable references"
        )

        data = yaml.safe_load(open("/app/services/ansible/deploy.yml"))
        has_vars = False
        for play in data:
            if "vars" in play or "vars_files" in play:
                has_vars = True
                break
        assert has_vars, "Playbook missing variable definitions (vars or vars_files)"
