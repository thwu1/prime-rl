"""
Tests that verify the configuration management pipeline correctly handles
a transient config-source inconsistency without cascading failures.

Properties under test:
  1. Config merger preserves all keys when sources disagree (fail-safe).
  2. Canary validation accepts both legacy (ip_blocks) and migrated
     (ip_ranges) field names.
  3. Canary validation result is awaited before the rollout proceeds.
  4. Site stale-entry cleanup does not exceed the health-check timeout.
  5. CircuitBreaker correctly tracks batch failures and trips at threshold.
  6. RolloutController integrates the circuit breaker to halt on failures.
  7. End-to-end two-phase migration scenario succeeds.
  8. Root cause analysis is present and well-structured.
"""

import json
import os
import sys
import time
import threading

import pytest

sys.path.insert(0, "/app")

from config_pipeline.store import DualSourceConfigStore
from config_pipeline.merger import merge_configs, deep_merge_keys
from config_pipeline.canary import CanaryValidator
from config_pipeline.rollout import RolloutController
from config_pipeline.site import SiteManager
from config_pipeline.health import HealthChecker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_store(tmp_path):
    return DualSourceConfigStore(str(tmp_path / "store"))


@pytest.fixture
def sample_config():
    return {
        "ip_blocks": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        "routing_rules": {"backend": "pool-1", "timeout": 5000},
        "service_endpoints": {"api": "api.internal:443", "db": "db.internal:5432"},
        "metadata": {"version": "1.0"},
    }


# ---------------------------------------------------------------------------
# 1. Config Merger Tests
# ---------------------------------------------------------------------------

class TestConfigMerger:

    def test_identical_sources_produce_same_config(self, sample_config):
        merged, inconsistent = merge_configs(sample_config, sample_config)
        assert not inconsistent
        assert merged == sample_config

    def test_key_only_in_primary_is_preserved(self, sample_config):
        """A key present only in primary must survive the merge (fail-safe)."""
        secondary = {k: v for k, v in sample_config.items() if k != "metadata"}
        merged, inconsistent = merge_configs(sample_config, secondary)
        assert inconsistent
        assert "metadata" in merged, \
            "Key unique to primary must be preserved in the merged config"
        assert merged["metadata"] == sample_config["metadata"]

    def test_key_only_in_secondary_is_preserved(self, sample_config):
        """A key present only in secondary must survive the merge (fail-safe)."""
        primary = {k: v for k, v in sample_config.items() if k != "metadata"}
        merged, inconsistent = merge_configs(primary, sample_config)
        assert inconsistent
        assert "metadata" in merged, \
            "Key unique to secondary must be preserved in the merged config"

    def test_deep_merge_keys_returns_union(self, sample_config):
        secondary = {k: v for k, v in sample_config.items() if k != "metadata"}
        result = deep_merge_keys(sample_config, secondary)
        expected = set(sample_config.keys()) | set(secondary.keys())
        assert result == expected, \
            f"deep_merge_keys must return the union; got {result}"

    def test_migration_scenario_preserves_both_field_names(self):
        """Simulates the ip_blocks -> ip_ranges migration with propagation
        delay.  Both the old and new key must appear in the merged config."""
        primary = {
            "ip_ranges": ["10.0.0.0/8", "172.16.0.0/12"],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
            "metadata": {"version": "2.0"},
        }
        secondary = {
            "ip_blocks": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
            "metadata": {"version": "1.0"},
        }
        merged, _ = merge_configs(primary, secondary)

        assert "ip_ranges" in merged, \
            "ip_ranges (primary-only) must survive the merge"
        assert "ip_blocks" in merged, \
            "ip_blocks (secondary-only) must survive the merge"
        assert "routing_rules" in merged
        assert "service_endpoints" in merged
        assert "metadata" in merged


# ---------------------------------------------------------------------------
# 2. Canary Validator Tests
# ---------------------------------------------------------------------------

class TestCanaryValidator:

    def test_canary_rejects_missing_all_ip_fields(self):
        """Config missing both ip_blocks and ip_ranges must be rejected."""
        canary = CanaryValidator(validation_delay=0.05)
        bad = {"routing_rules": {"x": 1}, "service_endpoints": {"y": "z"}}
        result = canary.validate_async(bad, "test-site")
        result.wait(timeout=5.0)
        assert result.is_completed
        assert result.success is False

    def test_canary_rejects_empty_ip_blocks(self):
        canary = CanaryValidator(validation_delay=0.05)
        bad = {
            "ip_blocks": [],
            "routing_rules": {"x": 1},
            "service_endpoints": {"y": "z"},
        }
        result = canary.validate_async(bad, "test-site")
        result.wait(timeout=5.0)
        assert result.is_completed
        assert result.success is False

    def test_canary_accepts_ip_blocks(self):
        """Legacy configs with ip_blocks must pass canary validation."""
        canary = CanaryValidator(validation_delay=0.05)
        config = {
            "ip_blocks": ["10.0.0.0/8", "172.16.0.0/12"],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
        }
        result = canary.validate_async(config, "test-site")
        result.wait(timeout=5.0)
        assert result.is_completed
        assert result.success is True, \
            "Canary must accept configs with ip_blocks"

    def test_canary_accepts_ip_ranges(self):
        """Post-migration configs with ip_ranges (not ip_blocks) must pass
        canary validation."""
        canary = CanaryValidator(validation_delay=0.05)
        config = {
            "ip_ranges": ["10.0.0.0/8", "172.16.0.0/12"],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
        }
        result = canary.validate_async(config, "test-site")
        result.wait(timeout=5.0)
        assert result.is_completed
        assert result.success is True, \
            "Canary must accept configs with ip_ranges as alternative to ip_blocks"

    def test_canary_rejects_empty_ip_ranges(self):
        """Config with empty ip_ranges must be rejected."""
        canary = CanaryValidator(validation_delay=0.05)
        bad = {
            "ip_ranges": [],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
        }
        result = canary.validate_async(bad, "test-site")
        result.wait(timeout=5.0)
        assert result.is_completed
        assert result.success is False, \
            "Canary must reject empty ip_ranges"


# ---------------------------------------------------------------------------
# 3. Canary / Rollout Integration Tests
# ---------------------------------------------------------------------------

class TestCanaryRollout:

    def test_rollout_blocks_on_canary_failure(self, clean_store, sample_config):
        """When the canary rejects a config, the rollout must return False.

        This verifies that the rollout controller actually *waits* for the
        asynchronous canary result rather than proceeding immediately.
        """
        clean_store.initialize(sample_config)

        bad_config = {"routing_rules": {"x": 1}}  # missing ip_blocks, service_endpoints

        site = SiteManager("canary-site", clean_store, sample_config)
        canary = CanaryValidator(validation_delay=0.3)
        rollout = RolloutController([site], canary, batch_size=1, batch_delay=0.1)

        result = rollout.execute_rollout(bad_config)
        assert result is False, \
            "Rollout must fail when canary rejects the config"

    def test_rollout_succeeds_with_valid_config(self, clean_store, sample_config):
        clean_store.initialize(sample_config)
        sites = [SiteManager(f"s-{i}", clean_store, sample_config) for i in range(4)]
        canary = CanaryValidator(validation_delay=0.05)
        rollout = RolloutController(sites, canary, batch_size=2, batch_delay=0.1)
        assert rollout.execute_rollout(sample_config) is True


# ---------------------------------------------------------------------------
# 4. Site Cleanup Performance Tests
# ---------------------------------------------------------------------------

class TestSiteCleanup:

    def test_cleanup_within_timeout(self, clean_store, sample_config):
        """Stale-entry cleanup must finish within the health-check timeout."""
        for i in range(25):
            h = sample_config.copy()
            h["metadata"] = {"version": f"0.{i}"}
            clean_store.primary.put_config(h)
            clean_store.secondary.put_config(h)
        clean_store.initialize(sample_config)

        site = SiteManager("perf-site", clean_store, sample_config)
        reduced = {k: v for k, v in sample_config.items() if k != "metadata"}

        start = time.time()
        site.apply_config(reduced)
        elapsed = time.time() - start

        assert elapsed < SiteManager.HEALTH_CHECK_TIMEOUT, (
            f"Cleanup took {elapsed:.2f}s, exceeding "
            f"{SiteManager.HEALTH_CHECK_TIMEOUT}s timeout"
        )
        assert site.is_healthy(), "Site must remain healthy after cleanup"

    def test_site_healthy_after_config_reduction(self, clean_store, sample_config):
        for i in range(20):
            clean_store.primary.put_config(sample_config)
            clean_store.secondary.put_config(sample_config)
        clean_store.initialize(sample_config)

        site = SiteManager("health-site", clean_store, sample_config)
        reduced = {k: v for k, v in sample_config.items() if k != "metadata"}
        site.apply_config(reduced)
        assert site.is_healthy(), "Site must be healthy after applying reduced config"


# ---------------------------------------------------------------------------
# 5. CircuitBreaker Unit Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def test_import(self):
        """CircuitBreaker must be importable and constructable."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        assert cb is not None

    def test_does_not_trip_below_threshold(self):
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        cb.record_batch(10, 2)  # 20% failure
        assert not cb.is_tripped()
        assert abs(cb.failure_rate() - 0.2) < 0.01

    def test_trips_at_threshold(self):
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        cb.record_batch(10, 5)  # exactly 50%
        assert cb.is_tripped(), \
            "Circuit breaker must trip when failure rate equals threshold"

    def test_trips_above_threshold(self):
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        cb.record_batch(10, 8)  # 80% failure
        assert cb.is_tripped()

    def test_stays_tripped_until_reset(self):
        """Once tripped, the circuit breaker stays tripped even if later
        batches have low failure rates."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        cb.record_batch(4, 4)  # 100% → trips
        assert cb.is_tripped()
        cb.record_batch(4, 0)  # 0% for this batch
        assert cb.is_tripped(), \
            "Breaker must stay tripped until explicitly reset"

    def test_rolling_window_failure_rate(self):
        """Failure rate is computed over the rolling window, not all time."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.9, window_size=2)
        cb.record_batch(4, 0)  # 0%
        cb.record_batch(4, 0)  # 0%
        cb.record_batch(4, 0)  # window = last 2: 0/8 = 0%
        assert abs(cb.failure_rate() - 0.0) < 0.01

    def test_rolling_window_drops_old_batches(self):
        """Old batches outside the window do not affect failure rate."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.9, window_size=2)
        cb.record_batch(4, 4)  # 100% — window_size=2, threshold=0.9
        cb.record_batch(4, 0)  # window=[100%, 0%] → rate=50%
        cb.record_batch(4, 0)  # window=[0%, 0%] → rate=0%
        assert abs(cb.failure_rate() - 0.0) < 0.01

    def test_reset_clears_state(self):
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        cb.record_batch(4, 4)
        assert cb.is_tripped()
        cb.reset()
        assert not cb.is_tripped()
        assert cb.failure_rate() == 0.0

    def test_empty_returns_zero(self):
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=3)
        assert not cb.is_tripped()
        assert cb.failure_rate() == 0.0

    def test_cumulative_across_batches(self):
        """Failure rate accumulates correctly across multiple batches."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=0.5, window_size=4)
        cb.record_batch(4, 1)  # 25%
        cb.record_batch(4, 1)  # cumulative: 2/8 = 25%
        assert not cb.is_tripped()
        cb.record_batch(4, 3)  # cumulative: 5/12 ≈ 41.7%
        assert not cb.is_tripped()
        cb.record_batch(4, 3)  # cumulative: 8/16 = 50%
        assert cb.is_tripped()


# ---------------------------------------------------------------------------
# 6. Rollout + CircuitBreaker Integration
# ---------------------------------------------------------------------------

class TestRolloutWithCircuitBreaker:

    def test_rollout_has_circuit_breaker(self, clean_store, sample_config):
        """RolloutController must have a circuit_breaker attribute."""
        from config_pipeline.circuit_breaker import CircuitBreaker
        clean_store.initialize(sample_config)
        sites = [SiteManager("x", clean_store, sample_config)]
        canary = CanaryValidator(validation_delay=0.05)
        rollout = RolloutController(sites, canary, batch_size=1, batch_delay=0.1)
        assert hasattr(rollout, "circuit_breaker"), \
            "RolloutController must have a circuit_breaker attribute"
        assert isinstance(rollout.circuit_breaker, CircuitBreaker), \
            "circuit_breaker must be an instance of CircuitBreaker"

    def test_rollout_halts_on_unhealthy_batch(self, tmp_path):
        """When most sites become unhealthy after config application, the
        circuit breaker should trip and halt the rollout before all batches
        are processed."""
        store = DualSourceConfigStore(str(tmp_path / "cb_halt"))
        config = {
            "ip_blocks": ["10.0.0.0/8"],
            "routing_rules": {"backend": "pool-1"},
            "service_endpoints": {"api": "api:443"},
        }
        store.initialize(config)

        # 7 sites: 1 canary + 6 remaining (3 batches of 2)
        sites = [SiteManager(f"halt-{i}", store, config) for i in range(7)]

        # Monkey-patch: all non-canary sites become unhealthy after apply
        apply_count = {"n": 0}
        for site in sites[1:]:
            _orig = site.apply_config
            def unhealthy_apply(cfg, _s=site, _o=_orig):
                r = _o(cfg)
                _s._healthy = False
                apply_count["n"] += 1
                return r
            site.apply_config = unhealthy_apply

        canary = CanaryValidator(validation_delay=0.05)
        rollout = RolloutController(sites, canary, batch_size=2, batch_delay=0.1)

        result = rollout.execute_rollout(config)
        assert result is False, "Rollout must fail when sites are unhealthy"

        # With a circuit breaker, rollout should halt before processing all
        # 6 remaining sites.  The exact number depends on threshold and
        # batch_size, but it must be strictly less than 6.
        assert apply_count["n"] < 6, (
            f"Circuit breaker should halt rollout early, but "
            f"{apply_count['n']}/6 remaining sites were processed"
        )


# ---------------------------------------------------------------------------
# 7. End-to-End Integration
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_full_rollout_with_source_inconsistency(self, tmp_path):
        """Full scenario: a config field migration during propagation delay
        must roll out safely, preserving all config keys and keeping sites
        healthy."""
        store = DualSourceConfigStore(str(tmp_path / "e2e"))

        config = {
            "ip_blocks": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
            "routing_rules": {"backend": "pool-1", "timeout": 5000},
            "service_endpoints": {"api": "api:443"},
            "metadata": {"version": "1.0"},
        }
        for i in range(15):
            store.primary.put_config(config)
            store.secondary.put_config(config)
        store.initialize(config)

        sites = [SiteManager(f"site-{i}", store, config) for i in range(6)]

        # Simulate migration: ip_blocks -> ip_ranges in primary only
        migrated = {
            "ip_ranges": ["10.0.0.0/8", "172.16.0.0/12"],
            "routing_rules": config["routing_rules"],
            "service_endpoints": config["service_endpoints"],
            "metadata": {"version": "2.0"},
        }
        store.update_config(migrated, propagation_delay=3.0)
        time.sleep(0.1)

        primary = store.get_primary_config()
        secondary = store.get_secondary_config()
        merged, _ = merge_configs(primary, secondary)

        # Merged must contain networking info from at least one source
        assert "ip_blocks" in merged or "ip_ranges" in merged, \
            "Merged config must retain networking info from at least one source"
        assert "routing_rules" in merged
        assert "service_endpoints" in merged
        assert "metadata" in merged
        assert len(merged.get("ip_blocks", []) or merged.get("ip_ranges", [])) > 0

        canary = CanaryValidator(validation_delay=0.05)
        rollout = RolloutController(sites, canary, batch_size=2, batch_delay=0.1)
        assert rollout.execute_rollout(merged) is True, \
            "Rollout must succeed with properly merged config"

        health = HealthChecker(sites)
        final = health.check_all()
        assert all(final.values()), f"All sites must be healthy: {final}"

        for site in sites:
            has_ip = "ip_blocks" in site.current_config or "ip_ranges" in site.current_config
            assert has_ip, f"{site.site_id} missing networking config"
            assert "routing_rules" in site.current_config
            assert "service_endpoints" in site.current_config

    def test_post_migration_steady_state(self, tmp_path):
        """After migration completes and both sources have ip_ranges,
        the pipeline must accept the post-migration config."""
        store = DualSourceConfigStore(str(tmp_path / "e2e_post"))

        # Both sources already converged on ip_ranges
        post_migration = {
            "ip_ranges": ["10.0.0.0/8", "172.16.0.0/12"],
            "routing_rules": {"backend": "pool-1", "timeout": 5000},
            "service_endpoints": {"api": "api:443"},
            "metadata": {"version": "2.0"},
        }
        store.initialize(post_migration)

        sites = [SiteManager(f"post-{i}", store, post_migration) for i in range(4)]

        merged, inconsistent = merge_configs(
            store.get_primary_config(),
            store.get_secondary_config(),
        )
        assert not inconsistent
        assert "ip_ranges" in merged

        canary = CanaryValidator(validation_delay=0.05)
        rollout = RolloutController(sites, canary, batch_size=2, batch_delay=0.1)
        assert rollout.execute_rollout(merged) is True, \
            "Post-migration rollout with ip_ranges must succeed"

        health = HealthChecker(sites)
        assert all(health.check_all().values())


# ---------------------------------------------------------------------------
# 8. Root Cause Analysis Validation
# ---------------------------------------------------------------------------

class TestRootCauseAnalysis:

    RCA_PATH = "/app/data/rca.json"

    def test_rca_file_exists(self):
        """Root cause analysis file must be present."""
        assert os.path.exists(self.RCA_PATH), \
            f"Root cause analysis file {self.RCA_PATH} must exist"

    def test_rca_valid_json(self):
        """RCA must be valid JSON."""
        with open(self.RCA_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "RCA must be a JSON object"

    def test_rca_has_defects_array(self):
        """RCA must contain a 'defects' array with sufficient entries."""
        with open(self.RCA_PATH) as f:
            data = json.load(f)
        assert "defects" in data, "RCA must have a 'defects' key"
        assert isinstance(data["defects"], list), "'defects' must be a list"
        assert len(data["defects"]) >= 4, \
            f"Expected at least 4 defects identified, got {len(data['defects'])}"

    def test_rca_defect_structure(self):
        """Each defect entry must have module, function, and description."""
        with open(self.RCA_PATH) as f:
            data = json.load(f)
        for i, defect in enumerate(data["defects"]):
            assert "module" in defect, \
                f"Defect {i} missing 'module' field"
            assert "function" in defect, \
                f"Defect {i} missing 'function' field"
            assert "description" in defect, \
                f"Defect {i} missing 'description' field"
            assert isinstance(defect["module"], str) and len(defect["module"]) > 0, \
                f"Defect {i} 'module' must be a non-empty string"
            assert isinstance(defect["function"], str) and len(defect["function"]) > 0, \
                f"Defect {i} 'function' must be a non-empty string"
            assert isinstance(defect["description"], str) and len(defect["description"]) > 10, \
                f"Defect {i} 'description' must be a descriptive string (>10 chars)"

    def test_rca_covers_key_modules(self):
        """RCA must identify defects across the affected pipeline modules."""
        with open(self.RCA_PATH) as f:
            data = json.load(f)
        modules_mentioned = set()
        for defect in data["defects"]:
            modules_mentioned.add(defect["module"])

        required = {"merger.py", "canary.py", "site.py"}
        for mod in required:
            assert any(mod in m for m in modules_mentioned), \
                f"RCA must identify a defect in {mod}, found modules: {modules_mentioned}"

        rollout_related = {"rollout.py", "circuit_breaker.py"}
        assert any(any(rm in m for m in modules_mentioned) for rm in rollout_related), \
            f"RCA must identify a defect in rollout.py or circuit_breaker.py, found: {modules_mentioned}"
