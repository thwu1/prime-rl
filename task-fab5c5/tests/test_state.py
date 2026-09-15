"""
Tests for cascading configuration failure investigation and hardening.

Verifies bug fixes (SQL filtering, atomic writes, proxy resilience),
configuration validation pipeline creation, architecture design document,
and incident report.

"""

import pytest
import json
import subprocess
import sqlite3
import os
import sys
import re


SHARD_DIR = "/app/db/shards"
FEATURE_FILE = "/app/features/bot_features.json"
CONFIG_FILE = "/app/config/settings.json"


def get_base_feature_count():
    """Get expected count from unmigrated shard."""
    conn = sqlite3.connect(os.path.join(SHARD_DIR, "shard_4.db"))
    count = conn.execute(
        "SELECT COUNT(DISTINCT name) FROM system_columns WHERE database='default'"
    ).fetchone()[0]
    conn.close()
    return count


def run_generator(shard_path):
    """Run feature generator targeting a specific shard."""
    return subprocess.run(
        [sys.executable, "/app/generator/generate.py", shard_path],
        capture_output=True, text=True, cwd="/app"
    )


class TestFeatureGenerator:
    """Tests for feature file generator bug fixes."""

    def test_correct_count_migrated_shard(self):
        """Generator must produce correct count from migrated shards.

        Migrated shards expose both 'default' and 'r0' metadata.
        The generator must filter to only 'default' database columns.
        """
        base_count = get_base_feature_count()
        result = run_generator(os.path.join(SHARD_DIR, "shard_0.db"))
        assert result.returncode == 0, f"Generator failed: {result.stderr}"

        with open(FEATURE_FILE) as f:
            data = json.load(f)
        assert len(data["features"]) == base_count, (
            f"Expected {base_count} from migrated shard, got {len(data['features'])}. "
            f"Generator likely not filtering by database name."
        )

    def test_correct_count_unmigrated_shard(self):
        """Generator must produce correct count from unmigrated shards."""
        base_count = get_base_feature_count()
        result = run_generator(os.path.join(SHARD_DIR, "shard_4.db"))
        assert result.returncode == 0, f"Generator failed: {result.stderr}"

        with open(FEATURE_FILE) as f:
            data = json.load(f)
        assert len(data["features"]) == base_count

    def test_no_duplicate_features(self):
        """No duplicate feature names in generated file."""
        result = run_generator(os.path.join(SHARD_DIR, "shard_0.db"))
        assert result.returncode == 0

        with open(FEATURE_FILE) as f:
            data = json.load(f)
        names = [f["name"] for f in data["features"]]
        assert len(names) == len(set(names)), (
            f"Found {len(names) - len(set(names))} duplicate feature names"
        )

    def test_all_shards_consistent(self):
        """All shards must produce identical feature count."""
        counts = []
        for sf in sorted(os.listdir(SHARD_DIR)):
            if not sf.endswith('.db'):
                continue
            result = run_generator(os.path.join(SHARD_DIR, sf))
            assert result.returncode == 0, f"Failed on {sf}: {result.stderr}"
            with open(FEATURE_FILE) as f:
                data = json.load(f)
            counts.append((sf, len(data["features"])))

        first = counts[0][1]
        for sf, c in counts:
            assert c == first, (
                f"{sf} produced {c}, expected {first}. "
                f"Counts must be consistent across all shards."
            )

    def test_generator_query_has_database_filter(self):
        """Generator SQL must filter by database name."""
        with open("/app/generator/generate.py") as f:
            source = f.read()
        assert re.search(
            r"""database\s*=\s*['"]default['"]""", source, re.IGNORECASE
        ), "Generator query must include database='default' filter"

    def test_generator_uses_atomic_write(self):
        """Generator must use atomic file writes (temp file + rename).

        Writing directly to the output creates a window where the proxy
        reads partial/empty JSON during regeneration cycles.
        """
        with open("/app/generator/generate.py") as f:
            source = f.read()

        has_atomic = any(p in source for p in [
            "os.rename", "os.replace", "shutil.move",
            "tempfile", "tmp_path", ".tmp"
        ])
        assert has_atomic, (
            "Generator must use atomic file writes. "
            "Current approach truncates the file before writing, "
            "creating a TOCTOU window. Use write-to-temp + rename."
        )


class TestProxyServer:
    """Tests for FL2 proxy server resilience."""

    def test_proxy_starts_with_valid_features(self):
        """Proxy starts and serves with valid feature config."""
        run_generator(os.path.join(SHARD_DIR, "shard_4.db"))

        result = subprocess.run(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, '/app')
from proxy.server import ProxyServer
server = ProxyServer()
server.initialize()
result = server.handle_request({"user_agent_entropy": 0.5, "request_rate_1m": 10})
assert result["status"] == 200
print("OK")
"""],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Proxy failed: {result.stderr}"
        assert "OK" in result.stdout

    def test_proxy_handles_oversized_config(self):
        """Proxy must NOT crash on oversized config — fail-open required.

        Configuration issues must cause degraded service, not total outage.
        The proxy should truncate, log, and continue in degraded mode.
        """
        oversized = {
            "version": 2, "generated_at": "2025-11-18T11:25:00",
            "shard_source": "test_oversized",
            "features": [
                {"name": f"test_feature_{i}", "type": "Float64",
                 "enabled": True, "weight": 1.0}
                for i in range(250)
            ],
            "feature_count": 250
        }
        os.makedirs("/app/features", exist_ok=True)
        with open(FEATURE_FILE, "w") as f:
            json.dump(oversized, f)

        result = subprocess.run(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, '/app')
from proxy.server import ProxyServer
server = ProxyServer()
try:
    server.initialize()
    result = server.handle_request({"user_agent_entropy": 0.5})
    assert result["status"] in (200, 503)
    print("GRACEFUL")
except SystemExit:
    print("CRASHED_SYSTEMEXIT")
    sys.exit(1)
except RuntimeError as e:
    if any(w in str(e).lower() for w in ["unwrap", "panic", "featurelimit"]):
        print("CRASHED_PANIC")
        sys.exit(1)
    print("GRACEFUL")
"""],
            capture_output=True, text=True, timeout=30
        )
        assert "CRASHED" not in result.stdout, (
            f"Proxy crashed on oversized config. Must fail-open. "
            f"Output: {result.stdout}. Stderr: {result.stderr}"
        )
        assert result.returncode == 0


class TestConfigValidator:
    """Tests for the configuration validation pipeline.

    The solver must create /app/config_safety/validator.py that exports
    validate_config(data: dict) -> tuple[bool, list[str]].
    """

    def test_validator_module_exists(self):
        """Validator module must exist at /app/config_safety/validator.py."""
        assert os.path.exists("/app/config_safety/validator.py"), (
            "Configuration validator not found at /app/config_safety/validator.py. "
            "This module must be created to prevent future cascading failures."
        )

    def test_validator_is_importable(self):
        """Validator must be importable with correct interface."""
        result = subprocess.run(
            [sys.executable, "-c", """
import sys
sys.path.insert(0, '/app/config_safety')
from validator import validate_config
import inspect
sig = inspect.signature(validate_config)
assert len(sig.parameters) >= 1, "validate_config must accept at least 1 parameter"
print("OK")
"""],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Failed to import validate_config: {result.stderr}"
        )

    def test_validator_accepts_valid_config(self):
        """Validator must accept a correctly-formed configuration."""
        run_generator(os.path.join(SHARD_DIR, "shard_4.db"))

        result = subprocess.run(
            [sys.executable, "-c", """
import sys, json
sys.path.insert(0, '/app/config_safety')
from validator import validate_config
with open('/app/features/bot_features.json') as f:
    data = json.load(f)
valid, errors = validate_config(data)
assert valid, f"Validator rejected valid config: {errors}"
print("OK")
"""],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Validator rejected valid config: {result.stdout} {result.stderr}"
        )

    def test_validator_rejects_oversized_config(self):
        """Validator must reject configs exceeding MAX_FEATURES."""
        result = subprocess.run(
            [sys.executable, "-c", """
import sys, json
sys.path.insert(0, '/app/config_safety')
from validator import validate_config
bad = {
    "version": 2, "generated_at": "test", "shard_source": "test",
    "features": [{"name": f"f_{i}", "type": "Float64", "enabled": True, "weight": 0.01}
                 for i in range(250)],
    "feature_count": 250
}
valid, errors = validate_config(bad)
assert not valid, "Validator should reject config with 250 features"
assert any("feature" in e.lower() or "limit" in e.lower() or "exceed" in e.lower()
           or "count" in e.lower() or "200" in e for e in errors), \
    f"Error should mention feature limit: {errors}"
print("OK")
"""],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Validator failed to reject oversized config: {result.stdout} {result.stderr}"
        )

    def test_validator_rejects_duplicate_features(self):
        """Validator must reject configs with duplicate feature names."""
        result = subprocess.run(
            [sys.executable, "-c", """
import sys, json
sys.path.insert(0, '/app/config_safety')
from validator import validate_config
bad = {
    "version": 2, "generated_at": "test", "shard_source": "test",
    "features": [
        {"name": "feat_a", "type": "Float64", "enabled": True, "weight": 0.5},
        {"name": "feat_b", "type": "Float64", "enabled": True, "weight": 0.3},
        {"name": "feat_a", "type": "Float64", "enabled": True, "weight": 0.5},
    ],
    "feature_count": 3
}
valid, errors = validate_config(bad)
assert not valid, "Validator should reject config with duplicate names"
assert any("duplicate" in e.lower() or "unique" in e.lower() for e in errors), \
    f"Error should mention duplicates: {errors}"
print("OK")
"""],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Validator failed to reject duplicates: {result.stdout} {result.stderr}"
        )

    def test_cfctl_validate_works(self):
        """cfctl config validate must work with the installed validator."""
        run_generator(os.path.join(SHARD_DIR, "shard_4.db"))

        result = subprocess.run(
            [sys.executable, "/app/cfctl", "config", "validate", FEATURE_FILE],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"cfctl config validate failed on valid config: "
            f"{result.stdout} {result.stderr}"
        )
        # Must not show the NOT IMPLEMENTED message
        assert "NOT IMPLEMENTED" not in result.stdout.upper()


class TestDesignDocument:
    """Tests for the architecture design document."""

    def test_design_doc_exists(self):
        """Design document must be written at /app/design_doc.md."""
        assert os.path.exists("/app/design_doc.md"), (
            "Design document not found at /app/design_doc.md"
        )

    def test_design_doc_substantive(self):
        """Design document must be substantive (>= 800 characters)."""
        with open("/app/design_doc.md") as f:
            content = f.read()
        assert len(content) >= 800, (
            f"Design document too brief ({len(content)} chars). "
            f"Must contain substantive architectural analysis."
        )

    def test_design_doc_evaluates_fail_open(self):
        """Design doc must evaluate fail-open vs fail-closed trade-offs."""
        with open("/app/design_doc.md") as f:
            content = f.read().lower()

        has_fail_analysis = (
            ("fail-open" in content or "fail open" in content) and
            ("fail-closed" in content or "fail closed" in content or
             "fail-close" in content or "fail close" in content)
        )
        has_concept = any(all(term in content for term in group) for group in [
            ["graceful", "degrad"],
            ["availability", "correctness"],
        ])
        assert has_fail_analysis or has_concept, (
            "Design document must evaluate fail-open vs fail-closed trade-offs "
            "for bot scoring when configuration is degraded."
        )

    def test_design_doc_discusses_deployment(self):
        """Design doc must discuss safe deployment strategies."""
        with open("/app/design_doc.md") as f:
            content = f.read().lower()

        has_deployment = any(term in content for term in [
            "canary", "gradual", "rolling", "staged",
            "rollout", "rollback", "deployment",
            "propagation", "phased"
        ])
        assert has_deployment, (
            "Design document must discuss safe deployment strategies "
            "(canary, gradual rollout, rollback mechanisms)."
        )

    def test_design_doc_discusses_validation(self):
        """Design doc must discuss configuration validation approach."""
        with open("/app/design_doc.md") as f:
            content = f.read().lower()

        has_validation = any(term in content for term in [
            "validat", "schema", "invariant", "constraint",
            "pre-deploy", "pre-flight", "check"
        ])
        assert has_validation, (
            "Design document must discuss configuration validation "
            "and the specific invariants enforced."
        )


class TestIncidentReport:
    """Tests for the incident report."""

    def test_incident_report_exists(self):
        """Incident report must exist at /app/incident_report.txt."""
        assert os.path.exists("/app/incident_report.txt")

    def test_incident_report_substantive(self):
        """Incident report must be substantive (>= 300 chars)."""
        with open("/app/incident_report.txt") as f:
            content = f.read()
        assert len(content) >= 300, (
            f"Incident report too short ({len(content)} chars)"
        )

    def test_incident_report_covers_cascade(self):
        """Report must describe both the database and proxy failure modes."""
        with open("/app/incident_report.txt") as f:
            content = f.read().lower()

        has_db = any(t in content for t in [
            "database", "query", "sql", "shard", "migration",
            "duplicate", "r0", "system_columns"
        ])
        has_proxy = any(t in content for t in [
            "feature", "limit", "200", "crash", "panic",
            "fail-open", "proxy", "truncat"
        ])
        assert has_db, "Report must discuss database root cause"
        assert has_proxy, "Report must discuss proxy failure mode"
