
"""
Tests for CDN configuration pipeline incident response.

Verifies:
1. Three root cause bugs are fixed
2. Database restored to pre-incident state
3. Circuit breaker module created with correct behavior
4. Circuit breaker integrated into the pipeline
5. Full end-to-end pipeline works
"""

import pytest
import json
import sys
import os
import sqlite3
import subprocess
import time

sys.path.insert(0, '/app')

DB_PATH = '/app/db/features.db'


# ────────────────────────────────────────────────────────────
# Bug Fix Tests
# ────────────────────────────────────────────────────────────

class TestFeatureQueryFix:
    """Bug 1: Feature query must not return duplicates from replica schema."""

    def test_feature_count_within_limit(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/features?table=http_requests_features')
            features = resp.get_json()
            assert len(features) <= 150, (
                f"Feature count {len(features)} suggests duplicates from "
                f"replica schema are being returned"
            )

    def test_no_duplicate_feature_names(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/features?table=http_requests_features')
            features = resp.get_json()
            names = [f['name'] for f in features]
            duplicates = len(names) - len(set(names))
            assert duplicates == 0, (
                f"Found {duplicates} duplicate feature names in response"
            )

    def test_only_default_schema(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/features?table=http_requests_features')
            features = resp.get_json()
            for f in features:
                if 'schema_name' in f:
                    assert f['schema_name'] == 'default', (
                        f"Feature '{f['name']}' is from schema "
                        f"'{f['schema_name']}', expected 'default'"
                    )


class TestPrefixCleanupFix:
    """Bug 2: ?pending_delete parameter must filter correctly
    regardless of whether a value is provided."""

    def test_pending_delete_no_value(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/prefixes?pending_delete')
            prefixes = resp.get_json()
            assert len(prefixes) <= 10, (
                f"Got {len(prefixes)} prefixes for ?pending_delete, "
                f"expected only ~5 pending ones"
            )
            for p in prefixes:
                assert p['pending_delete'] == 1, (
                    f"Prefix {p['id']} is not pending delete "
                    f"but was returned by ?pending_delete filter"
                )

    def test_pending_delete_with_value(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/prefixes?pending_delete=true')
            prefixes = resp.get_json()
            assert len(prefixes) <= 10
            for p in prefixes:
                assert p['pending_delete'] == 1

    def test_all_prefixes_without_filter(self):
        from api_server import app
        with app.test_client() as client:
            resp = client.get('/api/prefixes')
            prefixes = resp.get_json()
            assert len(prefixes) >= 40, (
                f"Expected ~50 total prefixes but got {len(prefixes)}"
            )


class TestConfigLoaderFix:
    """Bug 3: Config loader must handle oversized input gracefully
    instead of crashing."""

    def test_oversized_config_no_crash(self):
        from config_loader import load_features
        features = [
            {"name": f"feat_{i}", "type": "Float32",
             "enabled": True, "weight": 1.0}
            for i in range(250)
        ]
        config = {"features": features, "version": "test",
                  "feature_count": 250}
        path = '/tmp/test_oversized.json'
        with open(path, 'w') as f:
            json.dump(config, f)
        try:
            result = load_features(path)
            assert result is not None
            assert len(result) <= 200, (
                f"Result has {len(result)} features, should be <= 200"
            )
        except RuntimeError:
            pytest.fail(
                "Config loader crashed on oversized input instead of "
                "handling gracefully"
            )

    def test_deduplicated_result(self):
        from config_loader import load_features
        features = []
        for i in range(112):
            features.append(
                {"name": f"feat_{i}", "type": "Float32",
                 "enabled": True, "weight": 1.0}
            )
        for i in range(112):
            features.append(
                {"name": f"feat_{i}", "type": "Float32",
                 "enabled": True, "weight": 1.0}
            )
        config = {"features": features, "version": "test",
                  "feature_count": 224}
        path = '/tmp/test_dupes.json'
        with open(path, 'w') as f:
            json.dump(config, f)
        try:
            result = load_features(path)
        except RuntimeError:
            pytest.fail("Config loader crashed on duplicate input")
        assert len(result) <= 200, (
            f"Result has {len(result)} features, should be <= 200"
        )
        names = [f['name'] for f in result if f is not None]
        assert len(names) == len(set(names)), (
            "Result still contains duplicate feature names"
        )

    def test_normal_config_still_works(self):
        from config_loader import load_features
        features = [
            {"name": f"feat_{i}", "type": "Float32",
             "enabled": True, "weight": 1.0}
            for i in range(100)
        ]
        config = {"features": features, "version": "test",
                  "feature_count": 100}
        path = '/tmp/test_normal.json'
        with open(path, 'w') as f:
            json.dump(config, f)
        result = load_features(path)
        assert len(result) == 100


# ────────────────────────────────────────────────────────────
# Database Restoration Tests
# ────────────────────────────────────────────────────────────

class TestDatabaseRestoration:
    """Database must be restored to correct pre-incident state."""

    def test_non_pending_prefixes_advertised(self):
        """All non-pending prefixes must be re-advertised."""
        conn = sqlite3.connect(DB_PATH)
        non_pending_withdrawn = conn.execute(
            "SELECT COUNT(*) FROM prefixes "
            "WHERE pending_delete = 0 AND advertised = 0"
        ).fetchone()[0]
        conn.close()
        assert non_pending_withdrawn == 0, (
            f"{non_pending_withdrawn} non-pending prefixes are still "
            f"de-advertised"
        )

    def test_non_pending_prefix_count(self):
        """There should be exactly 45 non-pending advertised prefixes."""
        conn = sqlite3.connect(DB_PATH)
        advertised = conn.execute(
            "SELECT COUNT(*) FROM prefixes "
            "WHERE pending_delete = 0 AND advertised = 1"
        ).fetchone()[0]
        conn.close()
        assert advertised == 45, (
            f"Expected 45 non-pending advertised prefixes, got {advertised}"
        )

    def test_service_bindings_exist_for_non_pending(self):
        """Every non-pending prefix must have at least one service binding."""
        conn = sqlite3.connect(DB_PATH)
        non_pending_ids = conn.execute(
            "SELECT id FROM prefixes WHERE pending_delete = 0"
        ).fetchall()
        missing = []
        for (pid,) in non_pending_ids:
            count = conn.execute(
                "SELECT COUNT(*) FROM service_bindings WHERE prefix_id = ?",
                (pid,)
            ).fetchone()[0]
            if count == 0:
                missing.append(pid)
        conn.close()
        assert len(missing) == 0, (
            f"{len(missing)} prefixes missing service bindings: "
            f"{missing[:10]}"
        )

    def test_service_binding_types_match_prefix(self):
        """Service binding type must match the prefix's service_binding column."""
        conn = sqlite3.connect(DB_PATH)
        mismatches = conn.execute("""
            SELECT p.id, p.service_binding, sb.service_type
            FROM prefixes p
            JOIN service_bindings sb ON sb.prefix_id = p.id
            WHERE p.pending_delete = 0
              AND p.service_binding != sb.service_type
        """).fetchall()
        conn.close()
        assert len(mismatches) == 0, (
            f"Service binding type mismatches: {mismatches[:5]}"
        )

    def test_service_binding_config_valid_json(self):
        """Service binding config must be valid JSON with expected structure."""
        conn = sqlite3.connect(DB_PATH)
        configs = conn.execute(
            "SELECT sb.prefix_id, sb.config FROM service_bindings sb "
            "JOIN prefixes p ON p.id = sb.prefix_id "
            "WHERE p.pending_delete = 0"
        ).fetchall()
        conn.close()
        assert len(configs) > 0, "No service binding configs found"
        for pid, config_str in configs:
            assert config_str is not None, (
                f"Service binding config for prefix {pid} is NULL"
            )
            try:
                parsed = json.loads(config_str)
            except json.JSONDecodeError:
                pytest.fail(
                    f"Invalid JSON in service binding config for prefix "
                    f"{pid}: {config_str}"
                )
            assert isinstance(parsed, dict), (
                f"Config for prefix {pid} should be a JSON object"
            )
            assert 'region' in parsed, (
                f"Config for prefix {pid} missing 'region' key"
            )


# ────────────────────────────────────────────────────────────
# Circuit Breaker Tests
# ────────────────────────────────────────────────────────────

class TestCircuitBreaker:
    """Circuit breaker module must exist and enforce safety limits."""

    def test_module_importable(self):
        """Circuit breaker module must be importable with required functions."""
        from circuit_breaker import validate_cleanup_batch
        from circuit_breaker import validate_feature_count

    # -- validate_cleanup_batch --

    def test_small_batch_allowed(self):
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch([1, 2, 3], 100)
        assert safe is True, f"Small batch (3%) should be allowed: {reason}"
        assert isinstance(reason, str)

    def test_large_batch_rejected(self):
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch(list(range(20)), 100)
        assert safe is False, "Large batch (20%) should be rejected"

    def test_boundary_10pct_allowed(self):
        """Exactly 10% should NOT be considered 'exceeding' 10%."""
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch(list(range(10)), 100)
        assert safe is True, (
            f"Boundary batch (exactly 10%) should be allowed: {reason}"
        )

    def test_over_boundary_rejected(self):
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch(list(range(11)), 100)
        assert safe is False, "11% batch should be rejected"

    def test_empty_batch_allowed(self):
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch([], 100)
        assert safe is True, f"Empty batch should be allowed: {reason}"

    def test_zero_active_rejects(self):
        """When no prefixes are active, any withdrawal should be rejected."""
        from circuit_breaker import validate_cleanup_batch
        safe, reason = validate_cleanup_batch([1, 2], 0)
        assert safe is False, (
            "Should reject withdrawal when no active prefixes exist"
        )

    # -- validate_feature_count --

    def test_feature_count_normal(self):
        from circuit_breaker import validate_feature_count
        safe, reason = validate_feature_count(100, 200)
        assert safe is True, f"Normal count should be safe: {reason}"

    def test_feature_count_over_limit(self):
        from circuit_breaker import validate_feature_count
        safe, reason = validate_feature_count(250, 200)
        assert safe is False, "Over-limit count should be rejected"

    def test_feature_count_at_limit(self):
        """Count exactly at limit is not 'exceeding' it."""
        from circuit_breaker import validate_feature_count
        safe, reason = validate_feature_count(200, 200)
        assert safe is True, (
            f"Count at exactly the limit should be safe: {reason}"
        )

    def test_feature_count_warning_zone(self):
        """Count above 80% of limit should pass but with warning."""
        from circuit_breaker import validate_feature_count
        safe, reason = validate_feature_count(170, 200)
        assert safe is True, f"Warning zone should still be safe: {reason}"
        assert 'warn' in reason.lower(), (
            f"Reason should mention warning at 85% usage: {reason}"
        )

    # -- logging --

    def test_log_file_created(self):
        """Calling circuit breaker functions must create a log file."""
        from circuit_breaker import validate_cleanup_batch
        from circuit_breaker import validate_feature_count
        validate_cleanup_batch([1, 2], 100)
        validate_feature_count(50, 200)
        assert os.path.exists('/app/logs/circuit_breaker.log'), (
            "Circuit breaker log file was not created"
        )
        with open('/app/logs/circuit_breaker.log') as f:
            content = f.read()
        assert len(content) > 0, "Circuit breaker log file is empty"


# ────────────────────────────────────────────────────────────
# End-to-End Pipeline Tests
# ────────────────────────────────────────────────────────────

class TestEndToEnd:
    """Full pipeline must work after all fixes and integration."""

    @pytest.fixture(autouse=True)
    def ensure_db_restored(self):
        """Skip e2e tests if the database hasn't been restored."""
        conn = sqlite3.connect(DB_PATH)
        advertised = conn.execute(
            "SELECT COUNT(*) FROM prefixes WHERE advertised = 1"
        ).fetchone()[0]
        conn.close()
        if advertised < 40:
            pytest.skip("Database not restored — cannot run e2e test")
        yield

    def _run_pipeline(self):
        """Start API server and run pipeline, returning the result."""
        server = subprocess.Popen(
            [sys.executable, '/app/api_server.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(2)
            result = subprocess.run(
                [sys.executable, '/app/run_pipeline.py'],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    def test_full_pipeline_completes(self):
        result = self._run_pipeline()
        assert result.returncode == 0, (
            f"Pipeline failed with rc={result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_pipeline_preserves_non_pending(self):
        self._run_pipeline()
        conn = sqlite3.connect(DB_PATH)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM prefixes WHERE advertised = 1"
        ).fetchone()[0]
        pending_still = conn.execute(
            "SELECT COUNT(*) FROM prefixes "
            "WHERE pending_delete = 1 AND advertised = 1"
        ).fetchone()[0]
        conn.close()
        assert remaining >= 40, (
            f"Only {remaining} prefixes still advertised — "
            f"cleanup deleted non-pending prefixes"
        )
        assert pending_still == 0, (
            f"{pending_still} pending-delete prefixes were not withdrawn"
        )

    def test_circuit_breaker_log_populated(self):
        self._run_pipeline()
        assert os.path.exists('/app/logs/circuit_breaker.log'), (
            "Circuit breaker log not created during pipeline run"
        )
        with open('/app/logs/circuit_breaker.log') as f:
            content = f.read()
        assert len(content) > 0, (
            "Circuit breaker log is empty after pipeline run"
        )
