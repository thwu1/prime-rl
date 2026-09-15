
import json
import os
from decimal import Decimal

import psycopg2
import psycopg2.errors
import pytest

DB_HOST = "127.0.0.1"
DB_NAME = "saas_platform"

CREDS = {
    "tenant_alpha": "alpha_app_2024",
    "tenant_beta": "beta_app_2024",
    "svc_reporting": "rpt_svc_2024",
    "dba_admin": "dba_master_2024",
}


def connect(user):
    return psycopg2.connect(
        dbname=DB_NAME, user=user, password=CREDS[user], host=DB_HOST
    )


# ============================================================
# Assessment Quality Tests
# ============================================================


class TestAssessment:
    @pytest.fixture(autouse=True)
    def load_assessment(self):
        assert os.path.exists("/app/assessment.json"), \
            "assessment.json must exist at /app/assessment.json"
        with open("/app/assessment.json") as f:
            self.data = json.load(f)

    def test_assessment_structure(self):
        assert isinstance(self.data, list), "assessment must be a JSON array"
        assert len(self.data) >= 5, "assessment must identify at least 5 vulnerabilities"
        for entry in self.data:
            assert "severity" in entry, "each entry must have a severity rating"
            assert "title" in entry or "id" in entry, "each entry must be identifiable"

    def test_covers_rls_bypass(self):
        text = json.dumps(self.data).lower()
        assert any(
            t in text
            for t in ["rls", "row level", "row-level", "security definer"]
        ), "assessment must identify the RLS bypass vulnerability"

    def test_covers_search_path(self):
        text = json.dumps(self.data).lower()
        assert any(
            t in text for t in ["search_path", "search path", "path injection"]
        ), "assessment must identify the search_path injection vulnerability"

    def test_covers_excessive_privilege(self):
        text = json.dumps(self.data).lower()
        has_priv = any(
            t in text
            for t in ["privilege", "create", "grant", "permission", "access control"]
        )
        has_context = any(
            t in text
            for t in ["schema", "tenant", "alpha", "ddl", "excessive", "unneeded"]
        )
        assert has_priv and has_context, \
            "assessment must identify excessive schema privileges for tenant users"

    def test_covers_file_traversal(self):
        text = json.dumps(self.data).lower()
        assert any(
            t in text
            for t in ["traversal", "path traversal", "file read", "pg_read_file", "export_backup"]
        ), "assessment must identify the file read / path traversal vulnerability"

    def test_covers_credential_exposure(self):
        text = json.dumps(self.data).lower()
        assert any(
            t in text
            for t in ["credential", "password", "cleartext", "plaintext", "secret"]
        ), "assessment must identify credential exposure"

    def test_severity_ratings(self):
        severities = [e.get("severity", "").lower() for e in self.data]
        critical_count = sum(1 for s in severities if s == "critical")
        assert critical_count >= 2, \
            "at least 2 vulnerabilities must be rated critical"


# ============================================================
# Hardening Verification: Attack Paths Must Be Closed
# ============================================================


class TestHardening:
    def test_v1_rls_bypass_closed(self):
        """tenant_alpha must NOT see tenant_beta data via monthly_summary"""
        conn = connect("tenant_alpha")
        conn.autocommit = True
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM saas.monthly_summary(2)")
            result = cur.fetchone()
            if result is not None:
                assert result[0] == 0 or result[0] == Decimal("0"), \
                    f"RLS bypass not fixed: tenant_alpha sees org 2 revenue={result[0]}"
        except psycopg2.DatabaseError:
            pass  # Function denying access is also acceptable
        finally:
            conn.close()

    def test_v2_search_path_pinned(self):
        """format_currency must have search_path pinned"""
        conn = connect("dba_admin")
        cur = conn.cursor()
        cur.execute("""
            SELECT proconfig
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE p.proname = 'format_currency' AND n.nspname = 'saas'
        """)
        row = cur.fetchone()
        conn.close()
        assert row is not None, "format_currency function must still exist"
        config = row[0]
        assert config is not None, \
            "format_currency must have proconfig (SET options) defined"
        config_str = str(config).lower()
        assert "search_path" in config_str, \
            "format_currency must pin search_path to prevent injection"

    def test_v3_schema_create_revoked(self):
        """tenant_alpha must NOT CREATE objects in saas schema"""
        conn = connect("tenant_alpha")
        conn.autocommit = True
        cur = conn.cursor()
        created = False
        try:
            cur.execute("CREATE TABLE saas._hardening_test (id integer)")
            created = True
        except psycopg2.DatabaseError:
            pass  # Expected
        finally:
            if created:
                try:
                    cur.execute("DROP TABLE IF EXISTS saas._hardening_test")
                except Exception:
                    pass
            conn.close()
        assert not created, \
            "tenant_alpha must not have CREATE privilege on saas schema"

    def test_v4_path_traversal_blocked(self):
        """export_backup must reject path traversal"""
        conn = connect("svc_reporting")
        conn.autocommit = True
        cur = conn.cursor()
        traversal_blocked = False
        try:
            cur.execute("SELECT saas.export_backup('/backups/../etc/passwd')")
            cur.fetchone()
        except psycopg2.DatabaseError:
            traversal_blocked = True
        finally:
            conn.close()
        assert traversal_blocked, \
            "export_backup must block path traversal (/backups/../etc/passwd)"

    def test_v5_credentials_not_readable(self):
        """tenant_alpha must NOT read cleartext passwords from system_config"""
        conn = connect("tenant_alpha")
        conn.autocommit = True
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT value FROM saas.system_config "
                "WHERE key LIKE '%password%'"
            )
            rows = cur.fetchall()
            if rows:
                for row in rows:
                    val = str(row[0])
                    assert "R3pl1c4" not in val and "Sm7p" not in val, \
                        "Cleartext passwords must not be readable by tenant"
        except psycopg2.DatabaseError:
            pass  # Access revoked entirely is acceptable
        finally:
            conn.close()


# ============================================================
# Functional Integrity: Legitimate Operations Must Still Work
# ============================================================


class TestFunctionalIntegrity:
    def test_tenant_reads_own_invoices(self):
        """tenant_alpha must still query their own invoices"""
        conn = connect("tenant_alpha")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM saas.invoices WHERE org_id = 1")
        count = cur.fetchone()[0]
        conn.close()
        assert count > 0, "tenant_alpha must still read own invoices"

    def test_tenant_reads_own_org(self):
        """tenant_alpha must still read own organization"""
        conn = connect("tenant_alpha")
        cur = conn.cursor()
        cur.execute("SELECT name FROM saas.organizations WHERE org_id = 1")
        result = cur.fetchone()
        conn.close()
        assert result is not None and result[0] == "Acme Corp"

    def test_tenant_isolation_preserved(self):
        """tenant_alpha must NOT see tenant_beta direct data"""
        conn = connect("tenant_alpha")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM saas.invoices WHERE org_id = 2")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, "tenant isolation must be preserved"

    def test_reporting_generates_summary(self):
        """svc_reporting must still generate reports via monthly_summary"""
        conn = connect("svc_reporting")
        cur = conn.cursor()
        cur.execute("SELECT * FROM saas.monthly_summary(1)")
        result = cur.fetchone()
        conn.close()
        assert result is not None, "monthly_summary must return data"
        assert result[0] > 0, \
            f"svc_reporting must see org 1 revenue, got {result[0]}"

    def test_format_currency_works(self):
        """format_currency must still return correctly formatted values"""
        conn = connect("tenant_alpha")
        cur = conn.cursor()
        cur.execute("SELECT saas.format_currency(1234.56)")
        result = cur.fetchone()[0]
        conn.close()
        assert result is not None, "format_currency must return a value"
        assert "1234.56" in result, \
            f"format_currency must format correctly, got: {result}"

    def test_backup_export_valid_path(self):
        """export_backup must still work for legitimate paths"""
        conn = connect("svc_reporting")
        cur = conn.cursor()
        cur.execute("SELECT saas.export_backup('/backups/manifest.txt')")
        result = cur.fetchone()[0]
        conn.close()
        assert "backup_manifest" in result, \
            "export_backup must work for valid paths under /backups/"
