"""
Tests for the CDN configuration pipeline incident response.

Verifies that all root causes are fixed, the circuit breaker is implemented,
and the pipeline validator is functional.

"""
import json
import os
import shutil
import subprocess

import pytest


@pytest.fixture(autouse=True)
def preserve_prefix_data():
    """Backup and restore prefix data before/after each test."""
    src = "/app/data/prefixes.json"
    backup = "/tmp/prefixes_test_backup.json"
    if os.path.exists(src):
        shutil.copy2(src, backup)
    yield
    if os.path.exists(backup):
        shutil.copy2(backup, src)


class TestConfigGenerator:
    """Tests for the config generator producing correct output."""

    def test_correct_feature_count(self):
        """Config generator must produce features only from the primary schema."""
        result = subprocess.run(
            ["python3", "/app/configgen/generate.py"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Generator failed: {result.stderr}"

        with open("/app/config/features.json") as f:
            config = json.load(f)

        count = config["feature_count"]
        assert count <= 110, (
            f"Feature count {count} suggests duplicate rows are included. "
            f"The query is returning data from multiple sources."
        )
        assert count > 50, (
            f"Feature count {count} is unexpectedly low — "
            f"features from the primary source may be missing."
        )
        assert count == len(config["features"]), (
            "feature_count field does not match actual features array length"
        )

    def test_no_duplicate_features(self):
        """Generated config must not contain duplicate feature names."""
        subprocess.run(
            ["python3", "/app/configgen/generate.py"],
            capture_output=True, text=True
        )
        with open("/app/config/features.json") as f:
            config = json.load(f)

        feature_names = [f["name"] for f in config["features"]]
        duplicates = [n for n in feature_names if feature_names.count(n) > 1]
        assert len(feature_names) == len(set(feature_names)), (
            f"Config contains duplicate feature names: {set(duplicates)}"
        )


class TestConfigLoader:
    """Tests for the Rust config loader resilience."""

    def test_graceful_on_oversized_config(self):
        """Loader must not panic on configs exceeding the feature limit."""
        oversized = {
            "version": "2.1",
            "model_id": "test_oversized",
            "features": [
                {"name": f"test_feat_{i}", "type": "Float64"}
                for i in range(250)
            ],
            "feature_count": 250,
        }
        config_path = "/tmp/oversized_config.json"
        with open(config_path, "w") as f:
            json.dump(oversized, f)

        result = subprocess.run(
            ["/app/bin/config_loader", config_path],
            capture_output=True, text=True
        )
        assert "panicked" not in result.stderr, (
            f"Loader panicked instead of handling the error gracefully: {result.stderr}"
        )
        assert result.returncode == 0, (
            f"Loader should degrade gracefully (exit 0) on oversized config, "
            f"got exit code {result.returncode}. stderr: {result.stderr}"
        )

    def test_works_on_valid_config(self):
        """Loader must process valid configs successfully."""
        valid = {
            "version": "2.1",
            "model_id": "test_valid",
            "features": [
                {"name": f"valid_feat_{i}", "type": "Float64"}
                for i in range(100)
            ],
            "feature_count": 100,
        }
        config_path = "/tmp/valid_config.json"
        with open(config_path, "w") as f:
            json.dump(valid, f)

        result = subprocess.run(
            ["/app/bin/config_loader", config_path],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Loader failed on valid config: {result.stderr}"
        )
        assert '"status": "ok"' in result.stdout or '"status":"ok"' in result.stdout, (
            f"Expected ok status in output, got: {result.stdout}"
        )


class TestPrefixManager:
    """Tests for the prefix manager correctness."""

    def test_cleanup_only_removes_pending(self):
        """Cleanup must only delete prefixes with pending_delete status."""
        with open("/app/data/prefixes.json") as f:
            original = json.load(f)
        pending_count = sum(1 for p in original if p["status"] == "pending_delete")
        active_count = sum(1 for p in original if p["status"] != "pending_delete")

        assert pending_count == 4, f"Expected 4 pending prefixes, found {pending_count}"
        assert active_count == 16, f"Expected 16 active prefixes, found {active_count}"

        result = subprocess.run(
            ["/app/bin/prefixmgr", "cleanup"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Cleanup failed: {result.stderr}"

        with open("/app/data/prefixes.json") as f:
            remaining = json.load(f)

        assert remaining is not None, (
            "Prefix file is null/empty — cleanup deleted ALL prefixes "
            "instead of only those pending deletion."
        )
        assert isinstance(remaining, list), (
            f"Expected list of prefixes, got {type(remaining)}"
        )
        assert len(remaining) == active_count, (
            f"Expected {active_count} remaining prefixes after cleanup, "
            f"got {len(remaining)}. Only {pending_count} pending prefixes "
            f"should have been removed."
        )
        for p in remaining:
            assert p["status"] != "pending_delete", (
                f"Prefix {p['id']} ({p['cidr']}) still has pending_delete "
                f"status after cleanup"
            )

    def test_list_pending_filter(self):
        """Listing with pending_delete query must return only matching prefixes."""
        result = subprocess.run(
            ["/app/bin/prefixmgr", "list", "pending_delete"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"List failed: {result.stderr}"

        prefixes = json.loads(result.stdout)
        assert prefixes is not None, "List returned null"
        assert len(prefixes) > 0, (
            "No pending_delete prefixes returned — the query filter "
            "is not working correctly"
        )
        for p in prefixes:
            assert p["status"] == "pending_delete", (
                f"Prefix {p['id']} has status '{p['status']}', "
                f"expected 'pending_delete'"
            )


class TestCircuitBreaker:
    """Tests for the bulk-deletion circuit breaker."""

    def test_blocks_mass_deletion(self):
        """Circuit breaker must prevent cleanup from deleting >50% of prefixes."""
        # Create a scenario where 6 of 10 prefixes (60%) are pending_delete
        test_prefixes = [
            {
                "id": i,
                "cidr": f"10.{i}.0.0/24",
                "customer_id": f"test_{i:03d}",
                "status": "pending_delete" if i <= 6 else "active",
                "service_binding": "cdn",
            }
            for i in range(1, 11)
        ]
        with open("/app/data/prefixes.json", "w") as f:
            json.dump(test_prefixes, f)

        result = subprocess.run(
            ["/app/bin/prefixmgr", "cleanup"],
            capture_output=True, text=True
        )
        assert result.returncode != 0, (
            f"Circuit breaker should have blocked cleanup of 6/10 (60%) "
            f"prefixes, but cleanup succeeded. stdout: {result.stdout}"
        )

        # Verify no data was modified when circuit breaker triggered
        with open("/app/data/prefixes.json") as f:
            remaining = json.load(f)
        assert len(remaining) == 10, (
            f"Circuit breaker should prevent any data modification, but "
            f"{10 - len(remaining)} prefixes were deleted"
        )

    def test_allows_normal_cleanup(self):
        """Circuit breaker must allow cleanup when deletion is under 50%."""
        # 3 of 10 (30%) pending — should be allowed
        test_prefixes = [
            {
                "id": i,
                "cidr": f"10.{i}.0.0/24",
                "customer_id": f"test_{i:03d}",
                "status": "pending_delete" if i <= 3 else "active",
                "service_binding": "cdn",
            }
            for i in range(1, 11)
        ]
        with open("/app/data/prefixes.json", "w") as f:
            json.dump(test_prefixes, f)

        result = subprocess.run(
            ["/app/bin/prefixmgr", "cleanup"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Circuit breaker should allow cleanup of 3/10 (30%) prefixes, "
            f"but it was blocked: {result.stderr}"
        )

        with open("/app/data/prefixes.json") as f:
            remaining = json.load(f)
        assert len(remaining) == 7, (
            f"Expected 7 remaining prefixes after cleanup, got {len(remaining)}"
        )


class TestPipelineValidator:
    """Tests for the pre-deployment pipeline validator."""

    @pytest.fixture(autouse=True)
    def preserve_config(self):
        """Backup and restore config file around each test."""
        src = "/app/config/features.json"
        backup = "/tmp/config_validator_backup.json"
        if os.path.exists(src):
            shutil.copy2(src, backup)
        yield
        if os.path.exists(backup):
            shutil.copy2(backup, src)
        elif os.path.exists(src):
            os.remove(src)

    def test_passes_on_valid_config(self):
        """Validator must exit 0 when the pipeline config is valid."""
        valid = {
            "version": "2.1",
            "model_id": "test_valid",
            "features": [
                {"name": f"feat_{i}", "type": "Float64"}
                for i in range(100)
            ],
            "feature_count": 100,
        }
        with open("/app/config/features.json", "w") as f:
            json.dump(valid, f)

        result = subprocess.run(
            ["python3", "/app/validate_pipeline.py"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Validator should pass on valid config, but failed. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_detects_duplicate_features(self):
        """Validator must exit 1 when config contains duplicate feature names."""
        bad = {
            "version": "2.1",
            "model_id": "test_dupes",
            "features": [
                {"name": "feat_a", "type": "Float64"},
                {"name": "feat_b", "type": "Float64"},
                {"name": "feat_a", "type": "Float64"},
                {"name": "feat_c", "type": "Float64"},
                {"name": "feat_b", "type": "Float64"},
            ],
            "feature_count": 5,
        }
        with open("/app/config/features.json", "w") as f:
            json.dump(bad, f)

        result = subprocess.run(
            ["python3", "/app/validate_pipeline.py"],
            capture_output=True, text=True
        )
        assert result.returncode != 0, (
            f"Validator should detect duplicate features but exited 0. "
            f"stdout: {result.stdout}"
        )

    def test_detects_oversized_config(self):
        """Validator must exit 1 when feature count exceeds the system limit."""
        oversized = {
            "version": "2.1",
            "model_id": "test_oversized",
            "features": [
                {"name": f"feat_{i}", "type": "Float64"}
                for i in range(250)
            ],
            "feature_count": 250,
        }
        with open("/app/config/features.json", "w") as f:
            json.dump(oversized, f)

        result = subprocess.run(
            ["python3", "/app/validate_pipeline.py"],
            capture_output=True, text=True
        )
        assert result.returncode != 0, (
            f"Validator should detect oversized config but exited 0. "
            f"stdout: {result.stdout}"
        )


class TestEndToEnd:
    """End-to-end pipeline integration test."""

    def test_generate_and_load_pipeline(self):
        """Full pipeline: generate config then load it successfully."""
        gen_result = subprocess.run(
            ["python3", "/app/configgen/generate.py"],
            capture_output=True, text=True
        )
        assert gen_result.returncode == 0, (
            f"Config generator failed: {gen_result.stderr}"
        )

        load_result = subprocess.run(
            ["/app/bin/config_loader", "/app/config/features.json"],
            capture_output=True, text=True
        )
        assert "panicked" not in load_result.stderr, (
            f"Loader panicked on generated config: {load_result.stderr}"
        )
        assert load_result.returncode == 0, (
            f"Loader failed on generated config (exit {load_result.returncode}): "
            f"{load_result.stderr}"
        )
