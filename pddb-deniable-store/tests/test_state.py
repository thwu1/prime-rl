
import os
import sys
import json
import base64
import tempfile
import subprocess
import pytest

sys.path.insert(0, '/app')
from pddb import PDDB


@pytest.fixture
def tmp_image():
    fd, path = tempfile.mkstemp(suffix='.pddb')
    os.close(fd)
    os.unlink(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# =====================================================================
# Basic CRUD
# =====================================================================

class TestBasicCRUD:
    def test_create_and_read(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"alice@example.com")
        assert db.get("contacts", "alice") == b"alice@example.com"
        db.close()

    def test_update_value(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"old@mail.com")
        db.put("contacts", "alice", b"new@mail.com")
        assert db.get("contacts", "alice") == b"new@mail.com"
        db.close()

    def test_delete(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"data")
        assert db.delete("contacts", "alice") is True
        assert db.get("contacts", "alice") is None
        db.close()

    def test_get_nonexistent(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        assert db.get("contacts", "nobody") is None
        db.close()

    def test_list_keys(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"a")
        db.put("contacts", "bob", b"b")
        db.put("notes", "memo", b"m")
        keys = db.list_keys("contacts")
        assert "alice" in keys
        assert "bob" in keys
        assert "memo" not in keys
        db.close()

    def test_list_dictionaries(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"a")
        db.put("notes", "memo", b"m")
        dicts = db.list_dictionaries()
        assert "contacts" in dicts
        assert "notes" in dicts
        db.close()

    def test_empty_value(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("test", "empty", b"")
        assert db.get("test", "empty") == b""
        db.close()


# =====================================================================
# Multi-basis overlay semantics
# =====================================================================

class TestOverlaySemantics:
    def test_most_recent_basis_wins(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"public_data", basis=".System")
        db.create_basis("secret", "secretpass")
        db.put("contacts", "alice", b"private_data", basis="secret")
        assert db.get("contacts", "alice") == b"private_data"
        db.close()

    def test_lock_fallthrough(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"public_data", basis=".System")
        db.create_basis("secret", "secretpass")
        db.put("contacts", "alice", b"private_data", basis="secret")
        db.lock_basis("secret")
        assert db.get("contacts", "alice") == b"public_data"
        db.close()

    def test_explicit_basis_read(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"system_val", basis=".System")
        db.create_basis("other", "otherpass")
        db.put("contacts", "alice", b"other_val", basis="other")
        assert db.get("contacts", "alice", basis=".System") == b"system_val"
        assert db.get("contacts", "alice", basis="other") == b"other_val"
        db.close()

    def test_unlock_order(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        bases = db.get_unlocked_bases()
        assert bases == [".System"]
        db.create_basis("extra", "extrapass")
        bases = db.get_unlocked_bases()
        assert bases == [".System", "extra"]
        db.close()

    def test_list_keys_union(self, tmp_image):
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"a", basis=".System")
        db.create_basis("secret", "sp")
        db.put("contacts", "bob", b"b", basis="secret")
        keys = db.list_keys("contacts")
        assert set(keys) == {"alice", "bob"}
        db.close()


# =====================================================================
# Plausible deniability
# =====================================================================

class TestDeniability:
    def test_byte_distribution_uniform(self, tmp_image):
        """After locking a secret basis, the entire disk byte distribution must be uniform."""
        from scipy.stats import chisquare

        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("hidden", "hiddenpass")
        for i in range(20):
            db.put("secret_dict", f"key_{i}", os.urandom(2000), basis="hidden")
        db.lock_basis("hidden")
        db.close()

        with open(tmp_image, 'rb') as f:
            raw = f.read()

        counts = [0] * 256
        for b in raw:
            counts[b] += 1

        chi2, p_value = chisquare(counts)
        assert p_value > 0.001, f"Byte distribution non-uniform: chi2={chi2:.1f}, p={p_value:.6f}"

    def test_no_plaintext_leakage(self, tmp_image):
        """Known plaintext strings must not appear in the raw image after locking."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("hidden", "hiddenpass")
        marker = b"SUPER_SECRET_MARKER_STRING_12345"
        db.put("secrets", "marker", marker, basis="hidden")
        db.lock_basis("hidden")
        db.close()

        with open(tmp_image, 'rb') as f:
            raw = f.read()
        assert marker not in raw, "Plaintext leaked into disk image"

    def test_no_zero_pages(self, tmp_image):
        """No page should be all zeros — free pages must contain random data."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.close()

        with open(tmp_image, 'rb') as f:
            raw = f.read()
        page_size = 4096
        for i in range(len(raw) // page_size):
            page = raw[i * page_size:(i + 1) * page_size]
            assert page != b'\x00' * page_size, f"Page {i} is all zeros"

    def test_no_duplicate_pages(self, tmp_image):
        """No two pages should be identical."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("test", "testpass")
        for i in range(10):
            db.put("data", f"k{i}", os.urandom(1000), basis="test")
        db.close()

        with open(tmp_image, 'rb') as f:
            raw = f.read()
        page_size = 4096
        seen = set()
        for i in range(len(raw) // page_size):
            page = raw[i * page_size:(i + 1) * page_size]
            assert page not in seen, f"Duplicate page found at index {i}"
            seen.add(page)

    def test_no_zero_pages_after_operations(self, tmp_image):
        """Freed pages from put updates and deletes must contain random data, not zeros."""
        db = PDDB(tmp_image)
        db.format("syspass")
        for i in range(20):
            db.put("data", f"key_{i}", os.urandom(2000))
        for i in range(10):
            db.delete("data", f"key_{i}")
        db.close()

        with open(tmp_image, 'rb') as f:
            raw = f.read()
        page_size = 4096
        for i in range(len(raw) // page_size):
            page = raw[i * page_size:(i + 1) * page_size]
            assert page != b'\x00' * page_size, f"Page {i} is all zeros after delete operations"


# =====================================================================
# Churn
# =====================================================================

class TestChurn:
    def test_churn_changes_ciphertext(self, tmp_image):
        """After churn, all page data should differ from before."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("data", "key1", b"value_one")
        db.put("data", "key2", b"value_two" * 50)

        with open(tmp_image, 'rb') as f:
            before = f.read()

        db.churn()

        with open(tmp_image, 'rb') as f:
            after = f.read()

        page_size = 4096
        total = len(before) // page_size
        changed = sum(
            1 for i in range(total)
            if before[i * page_size:(i + 1) * page_size] != after[i * page_size:(i + 1) * page_size]
        )
        assert changed == total, f"Only {changed}/{total} pages changed after churn"
        db.close()

    def test_churn_preserves_data(self, tmp_image):
        """All stored data must be intact after churn."""
        db = PDDB(tmp_image)
        db.format("syspass")
        test_data = {f"key_{i}": os.urandom(500) for i in range(10)}
        for k, v in test_data.items():
            db.put("data", k, v)
        db.churn()
        for k, v in test_data.items():
            assert db.get("data", k) == v, f"Data for {k} corrupted after churn"
        db.close()


# =====================================================================
# Persistence
# =====================================================================

class TestPersistence:
    def test_close_and_reopen(self, tmp_image):
        """Data must survive a close/reopen cycle."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"alice_data")
        db.put("notes", "memo", b"important memo content")
        db.close()

        db2 = PDDB(tmp_image)
        assert db2.unlock_basis(".System", "syspass") is True
        assert db2.get("contacts", "alice") == b"alice_data"
        assert db2.get("notes", "memo") == b"important memo content"
        db2.close()

    def test_multi_basis_persistence(self, tmp_image):
        """Multiple bases must survive close/reopen independently."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("pub", "info", b"public", basis=".System")
        db.create_basis("private", "privpass")
        db.put("priv", "secret", b"classified", basis="private")
        db.close()

        db2 = PDDB(tmp_image)
        assert db2.unlock_basis(".System", "syspass") is True
        assert db2.get("pub", "info") == b"public"
        assert db2.get("priv", "secret") is None
        assert db2.unlock_basis("private", "privpass") is True
        assert db2.get("priv", "secret") == b"classified"
        db2.close()


# =====================================================================
# Security
# =====================================================================

class TestSecurity:
    def test_wrong_password(self, tmp_image):
        """Wrong password must fail to unlock a basis."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("vault", "correct_password")
        db.put("vault_data", "key", b"secret", basis="vault")
        db.lock_basis("vault")
        assert db.unlock_basis("vault", "wrong_password") is False
        assert db.is_basis_unlocked("vault") is False
        db.close()

    def test_key_derivation_deterministic(self, tmp_image):
        """Same (name, password) must produce the same key across sessions."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("test", "mypassword")
        db.put("dict", "key", b"deterministic_test_value", basis="test")
        db.close()

        db2 = PDDB(tmp_image)
        assert db2.unlock_basis(".System", "syspass") is True
        assert db2.unlock_basis("test", "mypassword") is True
        assert db2.get("dict", "key", basis="test") == b"deterministic_test_value"
        db2.close()

    def test_different_passwords_different_keys(self, tmp_image):
        """Different passwords must not cross-unlock a basis."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.create_basis("vault", "password_A")
        db.put("data", "secret", b"hidden", basis="vault")
        db.lock_basis("vault")
        assert db.unlock_basis("vault", "password_B") is False
        db.close()


# =====================================================================
# FastSpace Cache
# =====================================================================

class TestFastSpace:
    def test_fastspace_limits_disclosure(self, tmp_image):
        """The cache must not exceed the configured limit."""
        db = PDDB(tmp_image, fastspace_limit=8)
        db.format("syspass")
        count = db.get_fastspace_count()
        assert count > 0, "Cache should be populated after format"
        assert count <= 8, f"Cache {count} exceeds limit 8"
        db.close()

    def test_fastspace_decreases_on_put(self, tmp_image):
        """Allocating a page via put() must remove it from the cache."""
        db = PDDB(tmp_image, fastspace_limit=8)
        db.format("syspass")
        before = db.get_fastspace_count()
        db.put("dict", "key", b"value")
        after = db.get_fastspace_count()
        assert after == before - 1, f"Expected cache to decrease by 1: {before} -> {after}"
        db.close()

    def test_fastspace_increases_on_delete(self, tmp_image):
        """Freeing a page via delete() must add it to the cache when below limit."""
        db = PDDB(tmp_image, fastspace_limit=16)
        db.format("syspass")
        db.put("dict", "key", b"value")
        before = db.get_fastspace_count()
        db.delete("dict", "key")
        after = db.get_fastspace_count()
        assert after == before + 1, f"Expected cache to increase by 1: {before} -> {after}"
        db.close()

    def test_fastspace_survives_close_reopen(self, tmp_image):
        """The cache must persist across close/reopen cycles."""
        db = PDDB(tmp_image, fastspace_limit=8)
        db.format("syspass")
        for i in range(3):
            db.put("dict", f"key_{i}", b"data" * 10)
        count_before = db.get_fastspace_count()
        assert count_before > 0
        db.close()

        db2 = PDDB(tmp_image, fastspace_limit=8)
        assert db2.unlock_basis(".System", "syspass") is True
        count_after = db2.get_fastspace_count()
        assert count_after == count_before, \
            f"Cache not restored: {count_before} before close, {count_after} after reopen"
        db2.close()

    def test_fastspace_allocation_when_cache_empty(self, tmp_image):
        """When the cache is exhausted, allocation must fall back to disk scan."""
        db = PDDB(tmp_image, fastspace_limit=2)
        db.format("syspass")
        assert db.get_fastspace_count() == 2
        db.put("dict", "key1", b"a")
        db.put("dict", "key2", b"b")
        assert db.get_fastspace_count() == 0
        # This must succeed via disk scan fallback
        db.put("dict", "key3", b"c")
        assert db.get("dict", "key3") == b"c"
        db.close()


# =====================================================================
# Export / Import
# =====================================================================

class TestExport:
    def test_export_creates_valid_file(self, tmp_image):
        """export_basis must produce a well-formed JSON file."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"alice@example.com")
        export_path = tmp_image + ".export"
        try:
            db.export_basis(".System", "syspass", export_path)
            assert os.path.exists(export_path)
            with open(export_path) as f:
                data = json.load(f)
            assert data["version"] == 1
            assert isinstance(data["salt"], str) and len(data["salt"]) > 0
            assert len(data["entries"]) == 1
            entry = data["entries"][0]
            assert "dictionary" in entry
            assert "key" in entry
            assert "data_b64" in entry
            assert "hmac" in entry
        finally:
            db.close()
            if os.path.exists(export_path):
                os.unlink(export_path)

    def test_export_import_roundtrip(self, tmp_image):
        """Exported data must be importable into a different PDDB instance."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"alice@example.com")
        db.put("notes", "memo", b"important memo content")

        export_path = tmp_image + ".export"
        fd2, path2 = tempfile.mkstemp(suffix='.pddb')
        os.close(fd2)
        os.unlink(path2)
        try:
            db.export_basis(".System", "syspass", export_path)
            db.close()

            db2 = PDDB(path2)
            db2.format("newpass")
            db2.import_basis(export_path, ".System", "syspass")
            assert db2.get("contacts", "alice") == b"alice@example.com"
            assert db2.get("notes", "memo") == b"important memo content"
            db2.close()
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)
            if os.path.exists(path2):
                os.unlink(path2)

    def test_export_tampered_data_rejected(self, tmp_image):
        """Import must reject entries whose data has been tampered with."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("dict", "key", b"original_value")
        export_path = tmp_image + ".export"
        fd2, path2 = tempfile.mkstemp(suffix='.pddb')
        os.close(fd2)
        os.unlink(path2)
        try:
            db.export_basis(".System", "syspass", export_path)
            db.close()

            # Tamper with the data
            with open(export_path) as f:
                data = json.load(f)
            data["entries"][0]["data_b64"] = base64.b64encode(b"tampered").decode()
            with open(export_path, 'w') as f:
                json.dump(data, f)

            db2 = PDDB(path2)
            db2.format("pass2")
            with pytest.raises(ValueError, match="[Hh][Mm][Aa][Cc]|integrity|verification|tag|tamper"):
                db2.import_basis(export_path, ".System", "syspass")
            db2.close()
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)
            if os.path.exists(path2):
                os.unlink(path2)

    def test_export_wrong_password_rejected(self, tmp_image):
        """Import with wrong password must fail HMAC verification."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("dict", "key", b"value")
        export_path = tmp_image + ".export"
        fd2, path2 = tempfile.mkstemp(suffix='.pddb')
        os.close(fd2)
        os.unlink(path2)
        try:
            db.export_basis(".System", "syspass", export_path)
            db.close()

            db2 = PDDB(path2)
            db2.format("pass2")
            with pytest.raises(ValueError):
                db2.import_basis(export_path, ".System", "wrong_password")
            db2.close()
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)
            if os.path.exists(path2):
                os.unlink(path2)

    def test_export_unique_salt(self, tmp_image):
        """Each export must use a different random salt."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("dict", "key", b"value")

        path1 = tmp_image + ".export1"
        path2 = tmp_image + ".export2"
        try:
            db.export_basis(".System", "syspass", path1)
            db.export_basis(".System", "syspass", path2)

            with open(path1) as f:
                d1 = json.load(f)
            with open(path2) as f:
                d2 = json.load(f)

            assert d1["salt"] != d2["salt"], "Two exports must use different salts"
            # Different salts should produce different HMAC tags
            assert d1["entries"][0]["hmac"] != d2["entries"][0]["hmac"]
            db.close()
        finally:
            for p in [path1, path2]:
                if os.path.exists(p):
                    os.unlink(p)


# =====================================================================
# CLI Verification (openssl interop)
# =====================================================================

class TestCLIVerification:
    def test_verify_script_exists_and_uses_openssl(self):
        """The verification script must exist and use openssl dgst."""
        assert os.path.exists("/app/verify_export.sh"), \
            "verify_export.sh not found at /app/verify_export.sh"
        with open("/app/verify_export.sh") as f:
            content = f.read()
        assert "openssl" in content, "Script must use openssl"
        assert "dgst" in content, "Script must use openssl dgst"
        assert "hmac" in content.lower(), "Script must compute HMACs"

    def test_verify_script_succeeds_on_valid_export(self, tmp_image):
        """The script must report ALL_VERIFIED for a valid export."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("contacts", "alice", b"alice@example.com")
        db.put("notes", "memo", b"memo content here")
        export_path = tmp_image + ".export"
        try:
            db.export_basis(".System", "syspass", export_path)
            db.close()

            result = subprocess.run(
                ["bash", "/app/verify_export.sh", export_path, "syspass"],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, \
                f"Script failed (rc={result.returncode}): stdout={result.stdout}, stderr={result.stderr}"
            assert "ALL_VERIFIED" in result.stdout, \
                f"Expected ALL_VERIFIED in output: {result.stdout}"
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)

    def test_verify_script_fails_on_tampered_export(self, tmp_image):
        """The script must detect tampered HMAC tags."""
        db = PDDB(tmp_image)
        db.format("syspass")
        db.put("dict", "key", b"value")
        export_path = tmp_image + ".export"
        try:
            db.export_basis(".System", "syspass", export_path)
            db.close()

            # Tamper with the HMAC
            with open(export_path) as f:
                data = json.load(f)
            data["entries"][0]["hmac"] = "0" * 64
            with open(export_path, 'w') as f:
                json.dump(data, f)

            result = subprocess.run(
                ["bash", "/app/verify_export.sh", export_path, "syspass"],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode != 0, \
                f"Script should fail on tampered data (rc={result.returncode})"
            assert "FAILED" in result.stdout, \
                f"Expected FAILED in output: {result.stdout}"
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)
