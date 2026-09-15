
import subprocess
import re
import pytest
import yaml


# ============================================================
# Helper: extract a BIND view block from named.conf
# ============================================================

def _extract_view_block(content, view_name):
    """Return the text of a specific view block from named.conf."""
    pattern = rf'view\s+"{view_name}"\s*\{{'
    match = re.search(pattern, content)
    if not match:
        return None
    brace_count = 0
    start = match.start()
    for i in range(match.end() - 1, len(content)):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                return content[start:i + 1]
    return None


def _strip_comments(text):
    """Remove C-style and C++-style comments from BIND config text."""
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


# ============================================================
# DNS: named.conf structure and validation
# ============================================================

class TestNamedConf:

    def test_named_checkconf(self):
        """named-checkconf must pass on the completed named.conf."""
        result = subprocess.run(
            ["named-checkconf", "/app/dns/named.conf"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"named-checkconf failed:\n{result.stderr}"

    def test_views_exist(self):
        """Both internal and external views must be defined."""
        with open("/app/dns/named.conf") as f:
            content = _strip_comments(f.read())
        assert re.search(r'view\s+"internal"', content), "Missing view 'internal'"
        assert re.search(r'view\s+"external"', content), "Missing view 'external'"

    def test_view_ordering(self):
        """Internal view must be defined before external view."""
        with open("/app/dns/named.conf") as f:
            content = _strip_comments(f.read())
        int_pos = re.search(r'view\s+"internal"', content).start()
        ext_pos = re.search(r'view\s+"external"', content).start()
        assert int_pos < ext_pos, (
            "Internal view must appear before external view for correct "
            "match-clients precedence"
        )

    def test_tsig_key(self):
        """A TSIG key named 'xfer-key' with hmac-sha256 must be defined."""
        with open("/app/dns/named.conf") as f:
            content = _strip_comments(f.read())
        assert re.search(r'key\s+"xfer-key"', content), "Missing TSIG key 'xfer-key'"
        assert re.search(r'algorithm\s+hmac-sha256\s*;', content), (
            "TSIG key must use hmac-sha256 algorithm"
        )

    def test_internal_view_recursion(self):
        """Internal view must enable recursion."""
        with open("/app/dns/named.conf") as f:
            content = f.read()
        block = _extract_view_block(content, "internal")
        assert block is not None, "Could not extract internal view block"
        stripped = _strip_comments(block)
        assert re.search(r'recursion\s+yes\s*;', stripped), (
            "Internal view must have 'recursion yes'"
        )

    def test_external_view_no_recursion(self):
        """External view must disable recursion."""
        with open("/app/dns/named.conf") as f:
            content = f.read()
        block = _extract_view_block(content, "external")
        assert block is not None, "Could not extract external view block"
        stripped = _strip_comments(block)
        assert re.search(r'recursion\s+no\s*;', stripped), (
            "External view must have 'recursion no'"
        )

    def test_internal_view_has_reverse_zone(self):
        """Internal view must serve the reverse zone."""
        with open("/app/dns/named.conf") as f:
            content = f.read()
        block = _extract_view_block(content, "internal")
        assert block is not None, "Could not extract internal view block"
        assert "in-addr.arpa" in block, (
            "Internal view must contain the reverse zone (30.20.10.in-addr.arpa)"
        )

    def test_external_view_no_reverse_zone(self):
        """External view must NOT serve a reverse zone."""
        with open("/app/dns/named.conf") as f:
            content = f.read()
        block = _extract_view_block(content, "external")
        assert block is not None, "Could not extract external view block"
        assert "in-addr.arpa" not in block, (
            "External view must not contain a reverse zone"
        )

    def test_zone_transfer_uses_tsig(self):
        """Zone transfer configuration must reference the TSIG key."""
        with open("/app/dns/named.conf") as f:
            content = f.read()
        block = _extract_view_block(content, "internal")
        assert block is not None
        assert re.search(r'allow-transfer\s*\{[^}]*key\s+"?xfer-key"?', block), (
            "Internal view zones must use 'allow-transfer { key \"xfer-key\"; }'"
        )


# ============================================================
# DNS: forward zone validation (internal)
# ============================================================

class TestInternalForwardZone:

    def test_checkzone(self):
        """named-checkzone must pass on the internal forward zone."""
        result = subprocess.run(
            ["named-checkzone", "infra.example.com",
             "/app/dns/zones/db.infra.example.com.internal"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"named-checkzone (internal forward) failed:\n{result.stderr}\n{result.stdout}"
        )

    def test_apex_a_record(self):
        """Zone apex must have an A record pointing to internal lb (10.20.30.1)."""
        with open("/app/dns/zones/db.infra.example.com.internal") as f:
            content = f.read()
        assert re.search(
            r"^@\s+.*\bIN\s+A\s+10\.20\.30\.1\b", content, re.MULTILINE
        ), "Missing A record at zone apex (@ -> 10.20.30.1)"

    def test_no_cname_at_apex(self):
        """Zone apex must not have a CNAME record."""
        with open("/app/dns/zones/db.infra.example.com.internal") as f:
            content = f.read()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if re.match(r"^@\s+.*\bCNAME\b", stripped, re.IGNORECASE):
                pytest.fail("CNAME at zone apex is illegal per RFC 1034")

    def test_internal_ips(self):
        """A records must use internal (10.20.30.x) addresses."""
        with open("/app/dns/zones/db.infra.example.com.internal") as f:
            content = f.read()
        expected = {
            "ns1": "10.20.30.2",
            "ns2": "10.20.30.3",
            "web1": "10.20.30.10",
            "web2": "10.20.30.11",
            "web3": "10.20.30.12",
            "api1": "10.20.30.15",
            "api2": "10.20.30.16",
            "db1": "10.20.30.20",
            "mail": "10.20.30.25",
        }
        for host, ip in expected.items():
            pattern = rf"^{host}\s+.*\bIN\s+A\s+{re.escape(ip)}\b"
            assert re.search(pattern, content, re.MULTILINE), (
                f"Missing A record: {host} -> {ip}"
            )

    def test_ns_trailing_dots(self):
        """NS record targets must end with a trailing dot."""
        with open("/app/dns/zones/db.infra.example.com.internal") as f:
            content = f.read()
        ns_targets = re.findall(r"\bNS\s+(\S+)", content)
        for target in ns_targets:
            assert target.endswith("."), (
                f"NS target '{target}' missing trailing dot"
            )

    def test_mail_is_a_record(self):
        """Mail host must be an A record, not CNAME (RFC 2181)."""
        with open("/app/dns/zones/db.infra.example.com.internal") as f:
            content = f.read()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if re.match(r"^mail\s+.*\bCNAME\b", stripped, re.IGNORECASE):
                pytest.fail("mail must be A record, not CNAME (RFC 2181)")


# ============================================================
# DNS: forward zone validation (external)
# ============================================================

class TestExternalForwardZone:

    def test_checkzone(self):
        """named-checkzone must pass on the external forward zone."""
        result = subprocess.run(
            ["named-checkzone", "infra.example.com",
             "/app/dns/zones/db.infra.example.com.external"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"named-checkzone (external forward) failed:\n{result.stderr}\n{result.stdout}"
        )

    def test_apex_a_record(self):
        """Zone apex must have an A record pointing to external lb (203.0.113.1)."""
        with open("/app/dns/zones/db.infra.example.com.external") as f:
            content = f.read()
        assert re.search(
            r"^@\s+.*\bIN\s+A\s+203\.0\.113\.1\b", content, re.MULTILINE
        ), "Missing A record at zone apex (@ -> 203.0.113.1)"

    def test_external_ips(self):
        """A records must use external (203.0.113.x) addresses."""
        with open("/app/dns/zones/db.infra.example.com.external") as f:
            content = f.read()
        # web1-3 all map to VIP 203.0.113.10
        for host in ["web1", "web2", "web3"]:
            pattern = rf"^{host}\s+.*\bIN\s+A\s+203\.0\.113\.10\b"
            assert re.search(pattern, content, re.MULTILINE), (
                f"External zone: {host} must resolve to VIP 203.0.113.10"
            )
        # api1-2 map to VIP 203.0.113.15
        for host in ["api1", "api2"]:
            pattern = rf"^{host}\s+.*\bIN\s+A\s+203\.0\.113\.15\b"
            assert re.search(pattern, content, re.MULTILINE), (
                f"External zone: {host} must resolve to VIP 203.0.113.15"
            )
        # ns1, ns2, mail have their own external IPs
        for host, ip in [("ns1", "203.0.113.2"), ("ns2", "203.0.113.3"),
                         ("mail", "203.0.113.25")]:
            pattern = rf"^{host}\s+.*\bIN\s+A\s+{re.escape(ip)}\b"
            assert re.search(pattern, content, re.MULTILINE), (
                f"External zone: {host} must resolve to {ip}"
            )

    def test_no_db1_in_external(self):
        """db1 must not have a record in the external zone."""
        with open("/app/dns/zones/db.infra.example.com.external") as f:
            content = f.read()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if re.match(r"^db1\s+", stripped, re.IGNORECASE):
                pytest.fail("db1 must not have a record in the external zone")


# ============================================================
# DNS: reverse zone validation
# ============================================================

class TestReverseZone:

    def test_checkzone(self):
        """named-checkzone must pass on the reverse zone."""
        result = subprocess.run(
            ["named-checkzone", "30.20.10.in-addr.arpa",
             "/app/dns/zones/db.10.20.30"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"named-checkzone (reverse) failed:\n{result.stderr}\n{result.stdout}"
        )

    def test_all_ptr_records(self):
        """PTR records must exist for every host in the internal IP table."""
        with open("/app/dns/zones/db.10.20.30") as f:
            content = f.read()
        required = {
            "1": "lb.infra.example.com.",
            "2": "ns1.infra.example.com.",
            "3": "ns2.infra.example.com.",
            "10": "web1.infra.example.com.",
            "11": "web2.infra.example.com.",
            "12": "web3.infra.example.com.",
            "15": "api1.infra.example.com.",
            "16": "api2.infra.example.com.",
            "20": "db1.infra.example.com.",
            "25": "mail.infra.example.com.",
        }
        for octet, fqdn in required.items():
            pattern = rf"^{octet}\s+.*\bPTR\s+{re.escape(fqdn)}"
            assert re.search(pattern, content, re.MULTILINE), (
                f"Missing PTR: {octet} -> {fqdn}"
            )

    def test_ptr_trailing_dots(self):
        """All PTR targets must end with a trailing dot."""
        with open("/app/dns/zones/db.10.20.30") as f:
            content = f.read()
        # Only match PTR in non-comment lines
        targets = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(";"):
                continue
            targets.extend(re.findall(r"\bPTR\s+(\S+)", stripped))
        assert targets, "No PTR records found in reverse zone"
        for target in targets:
            assert target.endswith("."), (
                f"PTR target '{target}' missing trailing dot"
            )


# ============================================================
# HAProxy validation
# ============================================================

class TestHAProxy:

    def test_config_valid(self):
        """haproxy -c must pass on the configuration file."""
        result = subprocess.run(
            ["haproxy", "-c", "-f", "/app/haproxy/haproxy.cfg"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"haproxy -c failed:\n{result.stderr}"

    def test_stick_table(self):
        """Frontend must have a stick-table for rate limiting."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        assert re.search(r"stick-table\s+type\s+ip", content), (
            "Missing stick-table configuration in frontend"
        )
        assert re.search(r"http_req_rate", content), (
            "stick-table must store http_req_rate"
        )

    def test_rate_limit_deny(self):
        """Rate limiting must deny with HTTP 429."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        assert re.search(r"deny.*429|429.*deny", content), (
            "Missing rate limit deny rule with status 429"
        )

    def test_rate_limit_internal_exemption(self):
        """Rate limit deny must exempt the internal network."""
        with open("/app/haproxy/haproxy.cfg") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if "429" in stripped and "deny" in stripped:
                assert re.search(r"!.*internal", stripped, re.IGNORECASE), (
                    "Rate limit deny (429) must exempt internal network "
                    "(e.g., '!is_internal' condition)"
                )
                return
        pytest.fail("Rate limit deny (429) not found")

    def test_admin_restriction(self):
        """Admin paths must be restricted to internal network with 403 denial."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        assert re.search(r"deny.*403|403.*deny", content), (
            "Missing admin restriction deny rule with status 403"
        )
        assert re.search(r"path_beg\s+/admin", content), (
            "Missing ACL for /admin path"
        )

    def test_all_backends_defined(self):
        """All five required backends must be defined."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        required = ["web_servers", "api_v1_servers", "api_v2_servers",
                     "static_servers", "admin_servers"]
        backends = set(re.findall(r"^backend\s+(\S+)", content, re.MULTILINE))
        for name in required:
            assert name in backends, (
                f"Missing backend '{name}'. Defined: {backends}"
            )

    def test_api_version_routing(self):
        """ACL must check X-API-Version header for v2 routing."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        assert re.search(r"hdr\(?X-API-Version\)?", content, re.IGNORECASE), (
            "Missing ACL for X-API-Version header"
        )

    def test_backend_references_consistent(self):
        """All use_backend/default_backend must reference defined backends."""
        with open("/app/haproxy/haproxy.cfg") as f:
            content = f.read()
        backends = set(re.findall(r"^backend\s+(\S+)", content, re.MULTILINE))
        refs = set(re.findall(
            r"(?:default_backend|use_backend)\s+(\S+)", content
        ))
        for ref in refs:
            assert ref in backends, (
                f"Backend reference '{ref}' has no matching backend. "
                f"Defined: {backends}"
            )

    def test_acl_ordering(self):
        """Rate-limit deny must come before admin deny, which comes before routing."""
        with open("/app/haproxy/haproxy.cfg") as f:
            lines = f.readlines()

        rate_deny_pos = None
        admin_deny_pos = None
        first_use_backend_pos = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "429" in stripped and "deny" in stripped and rate_deny_pos is None:
                rate_deny_pos = i
            if "403" in stripped and "deny" in stripped and admin_deny_pos is None:
                admin_deny_pos = i
            if "use_backend" in stripped and first_use_backend_pos is None:
                first_use_backend_pos = i

        assert rate_deny_pos is not None, "Rate limit deny (429) not found"
        assert admin_deny_pos is not None, "Admin deny (403) not found"
        assert first_use_backend_pos is not None, "No use_backend found"

        assert rate_deny_pos < admin_deny_pos, (
            "Rate limit deny (429) must appear before admin deny (403)"
        )
        assert admin_deny_pos < first_use_backend_pos, (
            "Admin deny (403) must appear before use_backend routing"
        )

    def test_api_v2_before_v1_routing(self):
        """API v2 routing must come before generic API routing."""
        with open("/app/haproxy/haproxy.cfg") as f:
            lines = f.readlines()

        v2_pos = None
        v1_pos = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "use_backend" in stripped and "api_v2" in stripped and v2_pos is None:
                v2_pos = i
            if "use_backend" in stripped and "api_v1" in stripped and v1_pos is None:
                v1_pos = i

        assert v2_pos is not None, "use_backend for api_v2_servers not found"
        assert v1_pos is not None, "use_backend for api_v1_servers not found"
        assert v2_pos < v1_pos, (
            "API v2 routing must appear before generic API v1 routing"
        )


# ============================================================
# MariaDB init.sql validation
# ============================================================

class TestDatabase:

    def test_appuser_privileges(self):
        """appuser must have SELECT/INSERT/UPDATE/DELETE on appdb.* only."""
        with open("/app/db/init.sql") as f:
            content = f.read()
        grants = [
            line for line in content.splitlines()
            if "appuser" in line and line.strip().upper().startswith("GRANT")
        ]
        assert grants, "No GRANT for appuser found"
        for grant in grants:
            upper = grant.upper()
            assert "ALL" not in upper, (
                f"appuser must not have ALL PRIVILEGES: {grant}"
            )
            assert "*.*" not in grant, (
                f"appuser must not have global access (*.*): {grant}"
            )
            assert "appdb" in grant, (
                f"appuser must reference appdb: {grant}"
            )
            for priv in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                assert priv in upper, (
                    f"appuser missing {priv} privilege: {grant}"
                )

    def test_reporter_select_only(self):
        """reporter must have SELECT only on appdb.* and appdb_analytics.*."""
        with open("/app/db/init.sql") as f:
            content = f.read()
        grants = [
            line for line in content.splitlines()
            if "reporter" in line and line.strip().upper().startswith("GRANT")
        ]
        assert len(grants) >= 2, (
            f"reporter needs GRANT on both appdb and appdb_analytics, found {len(grants)}"
        )
        for grant in grants:
            upper = grant.upper()
            assert "ALL" not in upper, f"reporter must not have ALL: {grant}"
            assert "SELECT" in upper, f"reporter must have SELECT: {grant}"
            # Must not have write privileges
            for priv in ["INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]:
                assert priv not in upper, (
                    f"reporter must not have {priv}: {grant}"
                )

    def test_migrator_ddl_only(self):
        """migrator must have DDL privileges only (no data manipulation)."""
        with open("/app/db/init.sql") as f:
            content = f.read()
        grants = [
            line for line in content.splitlines()
            if "migrator" in line and line.strip().upper().startswith("GRANT")
        ]
        assert grants, "No GRANT for migrator found"
        for grant in grants:
            upper = grant.upper()
            assert "appdb" in grant, f"migrator must reference appdb: {grant}"
            # Must have DDL privileges
            for priv in ["CREATE", "ALTER", "DROP"]:
                assert priv in upper, f"migrator missing {priv}: {grant}"
            # Must NOT have DML privileges
            for priv in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                assert priv not in upper, (
                    f"migrator must not have {priv} (DDL only): {grant}"
                )

    def test_staging_admin_correct_database(self):
        """staging_admin must have ALL PRIVILEGES on appdb_staging.* only."""
        with open("/app/db/init.sql") as f:
            content = f.read()
        grants = [
            line for line in content.splitlines()
            if "staging_admin" in line and line.strip().upper().startswith("GRANT")
        ]
        assert grants, "No GRANT for staging_admin found"
        for grant in grants:
            assert "appdb_staging" in grant, (
                f"staging_admin must reference appdb_staging: {grant}"
            )
            assert "ALL" in grant.upper(), (
                f"staging_admin must have ALL PRIVILEGES: {grant}"
            )

    def test_flush_privileges(self):
        """init.sql must include FLUSH PRIVILEGES."""
        with open("/app/db/init.sql") as f:
            content = f.read().upper()
        assert "FLUSH PRIVILEGES" in content, "Missing FLUSH PRIVILEGES"


# ============================================================
# Ansible playbook validation
# ============================================================

class TestAnsible:

    def test_syntax_check(self):
        """ansible-playbook --syntax-check must pass."""
        result = subprocess.run(
            ["ansible-playbook", "--syntax-check",
             "-i", "/app/ansible/inventory.ini",
             "/app/ansible/playbook.yml"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Ansible syntax check failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_become(self):
        """Playbook must use become: true at play level."""
        with open("/app/ansible/playbook.yml") as f:
            playbook = yaml.safe_load(f)
        play = playbook[0]
        assert play.get("become") is True, (
            "Playbook must include 'become: true' at play level"
        )

    def test_handler_names_match_notifies(self):
        """Every notify directive must reference an existing handler name."""
        with open("/app/ansible/playbook.yml") as f:
            playbook = yaml.safe_load(f)
        play = playbook[0]
        handler_names = {h["name"] for h in play.get("handlers", [])}
        assert handler_names, "No handlers defined in playbook"

        for task in play.get("tasks", []):
            if "notify" not in task:
                continue
            notifies = task["notify"]
            if isinstance(notifies, str):
                notifies = [notifies]
            for name in notifies:
                assert name in handler_names, (
                    f"Task '{task.get('name')}' notifies '{name}' but no "
                    f"such handler exists. Available: {handler_names}"
                )
