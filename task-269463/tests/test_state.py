
import json
import os
import subprocess
import pytest

RCA_PATH = "/app/analysis/root_cause_analysis.json"
CONFIG_PATH = "/app/analysis/optimal_config.json"
TUNING_PATH = "/app/analysis/tuning_actions.sql"
SVG_PATH = "/app/analysis/cache_advisory.svg"


@pytest.fixture
def rca():
    with open(RCA_PATH) as f:
        return json.load(f)


@pytest.fixture
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ============================================================
# Root Cause Analysis Tests
# ============================================================

def test_rca_file_exists():
    assert os.path.exists(RCA_PATH), "root_cause_analysis.json not found at /app/analysis/"


def test_rca_valid_structure(rca):
    assert isinstance(rca, list), "root_cause_analysis.json must be a JSON array"
    assert len(rca) >= 3, f"Expected at least 3 root causes, got {len(rca)}"
    for entry in rca:
        assert "cause" in entry, "Each entry must have 'cause' key"
        assert "severity" in entry, "Each entry must have 'severity' key"
        assert "evidence" in entry, "Each entry must have 'evidence' key"
        assert "category" in entry, "Each entry must have 'category' key"
        assert entry["severity"] in ("critical", "high", "medium", "low"), (
            f"Invalid severity: {entry['severity']}"
        )


def test_rca_critical_cause_identified(rca):
    critical = [e for e in rca if e["severity"] == "critical"]
    assert len(critical) >= 1, "Must identify at least one critical root cause"
    combined = " ".join(
        e["cause"].lower() + " " + e.get("evidence", "").lower()
        for e in critical
    )
    keywords = ["pars", "literal", "cursor", "bind"]
    found = any(kw in combined for kw in keywords)
    assert found, (
        f"Critical root cause should relate to parsing/literal SQL. "
        f"Got: {[e['cause'][:80] for e in critical]}"
    )


def test_rca_memory_issues_included(rca):
    categories = [e["category"] for e in rca]
    assert "memory" in categories, (
        f"Must identify memory-related issues. Categories found: {set(categories)}"
    )


def test_rca_severity_ordering(rca):
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [severity_rank.get(e["severity"], 4) for e in rca]
    assert ranks == sorted(ranks), (
        "Root causes must be ordered from highest to lowest severity"
    )


# ============================================================
# JSON Validation with jq
# ============================================================

def test_rca_jq_validation():
    """Validate root_cause_analysis.json parses cleanly with jq."""
    result = subprocess.run(
        ["jq", "type", RCA_PATH],
        capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"root_cause_analysis.json failed jq validation: {result.stderr}"
    )
    assert result.stdout.strip().strip('"') == "array", (
        f"jq reports type '{result.stdout.strip()}', expected 'array'"
    )


def test_config_jq_validation():
    """Validate optimal_config.json parses cleanly with jq."""
    result = subprocess.run(
        ["jq", "type", CONFIG_PATH],
        capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"optimal_config.json failed jq validation: {result.stderr}"
    )
    assert result.stdout.strip().strip('"') == "object", (
        f"jq reports type '{result.stdout.strip()}', expected 'object'"
    )


# ============================================================
# Optimal Config Tests
# ============================================================

def test_config_file_exists():
    assert os.path.exists(CONFIG_PATH), "optimal_config.json not found at /app/analysis/"


def test_config_db_cache_size(config):
    params = config["parameters"]
    cache = params.get("db_cache_size", 0)
    # Valid range from advisory: 384MB to 640MB
    assert 402653184 <= cache <= 671088640, (
        f"db_cache_size {cache} bytes not in expected range "
        f"[384MB=402653184, 640MB=671088640]"
    )


def test_config_pga_target(config):
    params = config["parameters"]
    pga = params.get("pga_aggregate_target", 0)
    # Must be at or above 240MB (first point where overallocation = 0)
    assert 251658240 <= pga <= 402653184, (
        f"pga_aggregate_target {pga} bytes not in expected range "
        f"[240MB=251658240, 384MB=402653184]"
    )


def test_config_cursor_sharing(config):
    params = config["parameters"]
    cursor = str(params.get("cursor_sharing", "")).upper().strip()
    assert cursor == "FORCE", (
        f"cursor_sharing should be 'FORCE', got '{cursor}'"
    )


def test_config_shared_pool_increased(config):
    params = config["parameters"]
    shared = params.get("shared_pool_size", 0)
    assert shared > 335544320, (
        f"shared_pool_size {shared} must be increased from current 320MB (335544320)"
    )


def test_config_budget_constraint(config):
    budget = config.get("memory_budget_used_bytes", 0)
    assert 0 < budget <= 1610612736, (
        f"Total SGA {budget} bytes must be positive and within "
        f"1.5GB budget (1610612736)"
    )


def test_config_cache_improvement_factor(config):
    factor = config.get("estimated_cache_improvement_factor", -1)
    assert 0.30 <= factor <= 0.55, (
        f"estimated_cache_improvement_factor {factor} not in expected "
        f"range [0.30, 0.55]"
    )


def test_config_ora_04031_count(config):
    count = config.get("ora_04031_count", -1)
    assert count == 5, f"ora_04031_count should be 5, got {count}"


def test_config_problematic_sql_f7k(config):
    sql_ids = set(config.get("problematic_sql_ids", []))
    assert "f7k2m9x8n4p1q" in sql_ids, (
        "Must identify SQL f7k2m9x8n4p1q as problematic"
    )


def test_config_problematic_sql_a3b(config):
    sql_ids = set(config.get("problematic_sql_ids", []))
    assert "a3b8c2d9e1f4g" in sql_ids, (
        "Must identify SQL a3b8c2d9e1f4g as problematic"
    )


# ============================================================
# Cache Advisory SVG Chart Tests
# ============================================================

def test_svg_file_exists():
    assert os.path.exists(SVG_PATH), "cache_advisory.svg not found at /app/analysis/"
    assert os.path.getsize(SVG_PATH) > 200, (
        f"cache_advisory.svg is suspiciously small ({os.path.getsize(SVG_PATH)} bytes)"
    )


def test_svg_valid_content():
    with open(SVG_PATH) as f:
        content = f.read()
    assert "<svg" in content.lower(), "File does not contain valid SVG markup"
    has_graphics = any(
        tag in content.lower()
        for tag in ["<path", "<polyline", "<line ", "<rect", "<circle"]
    )
    assert has_graphics, "SVG contains no graphical elements (path/polyline/line/rect/circle)"


def test_svg_has_advisory_labels():
    with open(SVG_PATH) as f:
        content = f.read().lower()
    has_label = any(
        word in content
        for word in ["cache", "buffer", "advisory", "physical read"]
    )
    assert has_label, "SVG chart missing expected axis/title labels related to cache advisory"


# ============================================================
# Tuning Actions Tests
# ============================================================

def test_tuning_file_exists():
    assert os.path.exists(TUNING_PATH), "tuning_actions.sql not found at /app/analysis/"


def test_tuning_has_cache_command():
    with open(TUNING_PATH) as f:
        content = f.read().lower()
    assert "db_cache_size" in content, (
        "tuning_actions.sql must contain ALTER SYSTEM SET for db_cache_size"
    )


def test_tuning_has_pga_command():
    with open(TUNING_PATH) as f:
        content = f.read().lower()
    assert "pga_aggregate_target" in content, (
        "tuning_actions.sql must contain ALTER SYSTEM SET for pga_aggregate_target"
    )


def test_tuning_has_cursor_sharing():
    with open(TUNING_PATH) as f:
        content = f.read().lower()
    assert "cursor_sharing" in content and "force" in content, (
        "tuning_actions.sql must set cursor_sharing to FORCE"
    )
