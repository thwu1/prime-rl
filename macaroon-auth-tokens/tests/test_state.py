"""
Tests for tkdb macaroon token verification service.

Verifies PKI infrastructure, database schema, key derivation, service
functionality, audit logging, and design evaluation.

"""

import pytest
import os
import sys
import subprocess
import sqlite3
import base64

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tkdb")


# ---------------------------------------------------------------------------
# PKI — certificates generated with openssl
# ---------------------------------------------------------------------------

class TestPKICertificateFiles:

    def test_ca_key_exists(self):
        assert os.path.isfile("/app/pki/ca.key"), "CA private key missing"

    def test_ca_cert_exists(self):
        assert os.path.isfile("/app/pki/ca.crt"), "CA certificate missing"

    def test_server_key_exists(self):
        assert os.path.isfile("/app/pki/server.key"), "Server private key missing"

    def test_server_cert_exists(self):
        assert os.path.isfile("/app/pki/server.crt"), "Server certificate missing"

    def test_ca_is_self_signed(self):
        r = subprocess.run(
            ["openssl", "verify", "-CAfile", "/app/pki/ca.crt", "/app/pki/ca.crt"],
            capture_output=True, text=True)
        assert r.returncode == 0 and "OK" in r.stdout, \
            f"CA cert not self-signed: {r.stderr}"

    def test_server_cert_signed_by_ca(self):
        r = subprocess.run(
            ["openssl", "verify", "-CAfile", "/app/pki/ca.crt", "/app/pki/server.crt"],
            capture_output=True, text=True)
        assert r.returncode == 0 and "OK" in r.stdout, \
            f"Server cert not signed by CA: {r.stderr}"

    def test_ca_uses_ecdsa_p256(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", "/app/pki/ca.crt", "-text", "-noout"],
            capture_output=True, text=True)
        assert "prime256v1" in r.stdout or "P-256" in r.stdout, \
            "CA cert must use ECDSA P-256 (prime256v1)"

    def test_server_uses_ecdsa_p256(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", "/app/pki/server.crt", "-text", "-noout"],
            capture_output=True, text=True)
        assert "prime256v1" in r.stdout or "P-256" in r.stdout, \
            "Server cert must use ECDSA P-256 (prime256v1)"

    def test_ca_cn_is_tkdb_ca(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", "/app/pki/ca.crt", "-subject", "-noout"],
            capture_output=True, text=True)
        assert "tkdb-ca" in r.stdout, "CA CN must be tkdb-ca"

    def test_server_cn_is_tkdb_server(self):
        r = subprocess.run(
            ["openssl", "x509", "-in", "/app/pki/server.crt", "-subject", "-noout"],
            capture_output=True, text=True)
        assert "tkdb-server" in r.stdout, "Server CN must be tkdb-server"


# ---------------------------------------------------------------------------
# Database — SQLite schema and initial data
# ---------------------------------------------------------------------------

class TestDatabaseSchema:

    def test_db_file_exists(self):
        assert os.path.isfile("/app/tkdb.db"), "Database file missing"

    def test_organizations_table_exists(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='organizations'")
        assert cur.fetchone() is not None, "organizations table missing"
        conn.close()

    def test_blacklist_table_exists(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='blacklist'")
        assert cur.fetchone() is not None, "blacklist table missing"
        conn.close()

    def test_audit_log_table_exists(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'")
        assert cur.fetchone() is not None, "audit_log table missing"
        conn.close()

    def test_organizations_has_required_columns(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("PRAGMA table_info(organizations)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {"id", "name", "encrypted_root_key", "nonce"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_blacklist_has_nonce_column(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("PRAGMA table_info(blacklist)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        assert "nonce" in cols, "blacklist must have nonce column"

    def test_audit_log_has_required_columns(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("PRAGMA table_info(audit_log)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {"operation", "token_identifier"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_initial_organizations_present(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("SELECT name FROM organizations ORDER BY id")
        orgs = [row[0] for row in cur.fetchall()]
        conn.close()
        assert "flyio-prod" in orgs, "flyio-prod org missing"
        assert "flyio-staging" in orgs, "flyio-staging org missing"
        assert "customer-acme" in orgs, "customer-acme org missing"

    def test_encrypted_root_keys_are_distinct(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("SELECT encrypted_root_key FROM organizations")
        keys = [row[0] for row in cur.fetchall()]
        conn.close()
        assert len(keys) == len(set(keys)), \
            "Each org must have a distinct encrypted root key"

    def test_nonces_are_12_bytes(self):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute("SELECT id, nonce FROM organizations")
        for org_id, nonce in cur.fetchall():
            assert len(nonce) == 12, \
                f"Org {org_id}: AES-GCM nonce must be 12 bytes, got {len(nonce)}"
        conn.close()


# ---------------------------------------------------------------------------
# Key Derivation — HKDF chain from CA key
# ---------------------------------------------------------------------------

class TestKeyDerivation:

    def test_master_key_decrypts_org_keys(self):
        """Master key derived via HKDF from CA must decrypt stored root keys."""
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        with open("/app/pki/ca.key", "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        ca_bytes = ca_key.private_numbers().private_value.to_bytes(32, "big")

        hkdf = HKDF(algorithm=hashes.SHA256(), length=32,
                     salt=b"tkdb-salt-2026", info=b"tkdb-master-key-v1")
        master_key = hkdf.derive(ca_bytes)

        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute(
            "SELECT encrypted_root_key, nonce FROM organizations WHERE id = 1")
        enc_key, nonce = cur.fetchone()
        conn.close()

        aesgcm = AESGCM(master_key)
        root_key = aesgcm.decrypt(nonce, enc_key, None)
        assert len(root_key) == 32, "Decrypted root key must be 32 bytes"

    def test_per_org_keys_match_hkdf_derivation(self):
        """Per-org root keys must match HKDF(master_key, info=org-root-key-{id})."""
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        with open("/app/pki/ca.key", "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        ca_bytes = ca_key.private_numbers().private_value.to_bytes(32, "big")

        hkdf = HKDF(algorithm=hashes.SHA256(), length=32,
                     salt=b"tkdb-salt-2026", info=b"tkdb-master-key-v1")
        master_key = hkdf.derive(ca_bytes)

        conn = sqlite3.connect("/app/tkdb.db")
        for org_id in [1, 2, 3]:
            cur = conn.execute(
                "SELECT encrypted_root_key, nonce FROM organizations WHERE id = ?",
                (org_id,))
            enc_key, nonce = cur.fetchone()
            aesgcm = AESGCM(master_key)
            actual_root_key = aesgcm.decrypt(nonce, enc_key, None)

            hkdf2 = HKDF(algorithm=hashes.SHA256(), length=32,
                         salt=b"tkdb-salt-2026",
                         info=f"org-root-key-{org_id}".encode())
            expected_root_key = hkdf2.derive(master_key)
            assert actual_root_key == expected_root_key, \
                f"Org {org_id}: root key does not match HKDF derivation"
        conn.close()


# ---------------------------------------------------------------------------
# Service — token lifecycle
# ---------------------------------------------------------------------------

class TestServiceIssuance:

    @pytest.fixture
    def svc(self):
        from service import TkdbService
        return TkdbService("/app/tkdb.db", "/app/pki")

    def test_issue_returns_token_and_identifier(self, svc):
        result = svc.issue("flyio-prod")
        assert "token" in result
        assert "identifier" in result
        assert result["identifier"].startswith("org:1:")

    def test_issue_different_orgs(self, svc):
        r1 = svc.issue("flyio-prod")
        r2 = svc.issue("flyio-staging")
        r3 = svc.issue("customer-acme")
        assert r1["identifier"].startswith("org:1:")
        assert r2["identifier"].startswith("org:2:")
        assert r3["identifier"].startswith("org:3:")

    def test_issue_with_caveats(self, svc):
        result = svc.issue("flyio-prod", caveats=["op = read", "app = myapp"])
        from macaroon import Macaroon
        m = Macaroon.deserialize(base64.b64decode(result["token"]))
        preds = [c["cid"] for c in m.caveats if "vid" not in c]
        assert "op = read" in preds
        assert "app = myapp" in preds


class TestServiceVerification:

    @pytest.fixture
    def svc(self):
        from service import TkdbService
        return TkdbService("/app/tkdb.db", "/app/pki")

    def test_verify_valid_token(self, svc):
        issued = svc.issue("flyio-prod")
        result = svc.verify(issued["token"])
        assert result["valid"] is True
        assert result["identifier"] == issued["identifier"]

    def test_verify_each_org(self, svc):
        for org in ["flyio-prod", "flyio-staging", "customer-acme"]:
            issued = svc.issue(org)
            result = svc.verify(issued["token"])
            assert result["valid"] is True, f"Token for {org} should verify"

    def test_verify_with_satisfiers(self, svc):
        issued = svc.issue("flyio-prod", caveats=["op = read"])
        result = svc.verify(issued["token"], satisfiers=["op = read"])
        assert result["valid"] is True

    def test_verify_caching_works(self, svc):
        issued = svc.issue("flyio-prod")
        r1 = svc.verify(issued["token"])
        r2 = svc.verify(issued["token"])
        assert r1["cached"] is False, "First verify should be a cache miss"
        assert r2["cached"] is True, "Second verify should be a cache hit"
        stats = svc.cache_stats()
        assert stats["hits"] >= 1
        assert stats["size"] >= 1


class TestServiceRevocation:

    @pytest.fixture
    def svc(self):
        from service import TkdbService
        return TkdbService("/app/tkdb.db", "/app/pki")

    def test_revoke_makes_token_invalid(self, svc):
        issued = svc.issue("flyio-prod")
        assert svc.verify(issued["token"])["valid"] is True
        svc.revoke(issued["identifier"])
        assert svc.verify(issued["token"])["valid"] is False

    def test_revoked_cached_token_rejected(self, svc):
        """Critical: token verified and cached, then revoked, must be rejected.
        This is the core test for Design C (revocation-first)."""
        issued = svc.issue("flyio-prod")
        # Verify and cache
        r1 = svc.verify(issued["token"])
        assert r1["valid"] is True
        assert r1["cached"] is False
        # Confirm cache hit
        r2 = svc.verify(issued["token"])
        assert r2["valid"] is True
        assert r2["cached"] is True
        # Revoke
        svc.revoke(issued["identifier"])
        # Verify after revocation — must be rejected despite being cached
        r3 = svc.verify(issued["token"])
        assert r3["valid"] is False, \
            "Revoked token must not be served as valid from cache"

    def test_get_revocations(self, svc):
        issued = svc.issue("flyio-prod")
        svc.revoke(issued["identifier"])
        revocations = svc.get_revocations()
        ids = [r["identifier"] for r in revocations]
        assert issued["identifier"] in ids


class TestServiceTokenDerivation:

    @pytest.fixture
    def svc(self):
        from service import TkdbService
        return TkdbService("/app/tkdb.db", "/app/pki")

    def test_derive_strips_specified_predicates(self, svc):
        issued = svc.issue("flyio-prod",
                           caveats=["op = read", "expires = 2026-12-31"])
        derived = svc.derive_service_token(
            issued["token"], strip_predicates=["expires"])
        assert derived["identifier"].startswith("svc:")
        from macaroon import Macaroon
        m = Macaroon.deserialize(base64.b64decode(derived["token"]))
        preds = [c["cid"] for c in m.caveats if "vid" not in c]
        assert "op = read" in preds, "Non-stripped caveats must be preserved"
        assert not any("expires" in p for p in preds), \
            "Stripped predicate prefix must be removed"

    def test_derived_token_verifies(self, svc):
        issued = svc.issue("flyio-prod", caveats=["op = read"])
        derived = svc.derive_service_token(issued["token"])
        result = svc.verify(derived["token"], satisfiers=["op = read"])
        assert result["valid"] is True

    def test_cache_stats_has_required_fields(self, svc):
        stats = svc.cache_stats()
        assert "size" in stats
        assert "hits" in stats
        assert "misses" in stats


# ---------------------------------------------------------------------------
# Audit Log — operations recorded
# ---------------------------------------------------------------------------

class TestAuditLog:

    @pytest.fixture
    def svc(self):
        from service import TkdbService
        return TkdbService("/app/tkdb.db", "/app/pki")

    def _get_ops_for(self, identifier):
        conn = sqlite3.connect("/app/tkdb.db")
        cur = conn.execute(
            "SELECT operation FROM audit_log WHERE token_identifier = ?",
            (identifier,))
        ops = [row[0] for row in cur.fetchall()]
        conn.close()
        return ops

    def test_issue_is_logged(self, svc):
        issued = svc.issue("flyio-prod")
        ops = self._get_ops_for(issued["identifier"])
        assert "issue" in ops, "issue operation must be logged"

    def test_verify_is_logged(self, svc):
        issued = svc.issue("flyio-prod")
        svc.verify(issued["token"])
        ops = self._get_ops_for(issued["identifier"])
        assert "verify" in ops, "verify operation must be logged"

    def test_revoke_is_logged(self, svc):
        issued = svc.issue("flyio-prod")
        svc.revoke(issued["identifier"])
        ops = self._get_ops_for(issued["identifier"])
        assert "revoke" in ops, "revoke operation must be logged"


# ---------------------------------------------------------------------------
# Evaluation — design analysis document
# ---------------------------------------------------------------------------

class TestEvaluation:

    def test_evaluation_file_exists(self):
        assert os.path.isfile("/app/EVALUATION.md"), \
            "Must create /app/EVALUATION.md with design evaluation"

    def test_selects_candidate_c(self):
        content = open("/app/EVALUATION.md").read().lower()
        assert any(phrase in content for phrase in [
            "candidate c", "design c", "option c", "approach c",
        ]), "Evaluation must select Candidate C as the correct design"

    def test_identifies_candidate_a_flaw(self):
        content = open("/app/EVALUATION.md").read().lower()
        a_mentioned = any(p in content for p in ["candidate a", "design a"])
        flaw_terms = ["stale", "bypass", "revok", "race", "invalid", "cache"]
        has_flaw = any(t in content for t in flaw_terms)
        assert a_mentioned and has_flaw, \
            "Evaluation must identify the security flaw in Candidate A"

    def test_evaluation_has_substantive_analysis(self):
        content = open("/app/EVALUATION.md").read().lower()
        security_terms = ["revoc", "cache", "security", "attack", "vulnerab",
                          "blacklist", "stale", "race", "toctou"]
        matches = sum(1 for t in security_terms if t in content)
        assert matches >= 3, \
            "Evaluation must contain substantive security analysis"
