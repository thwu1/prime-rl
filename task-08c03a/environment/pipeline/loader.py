"""Configuration loader for the partition reconciliation pipeline.

Loads source configurations from YAML and cross-validates
against the SQLite instrument registry.
"""

import yaml
import sqlite3
from pathlib import Path

CONFIG_PATH = Path("/app/pipeline.yaml")
COST_CONFIG_PATH = Path("/app/cost_config.yaml")
DB_PATH = Path("/app/partitions.db")


def load_yaml_config():
    """Load and return the parsed YAML configuration."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_sources_config():
    """Build source configuration dict from YAML.

    Returns:
        Dict mapping source names to config dicts with keys:
        'instruments' (list), 'available_dates' (list), 'priority' (int).
    """
    config = load_yaml_config()
    sources = {}
    for name, cfg in config.get("sources", {}).items():
        sources[name] = {
            "instruments": cfg.get("instruments", []),
            "available_dates": cfg.get("available_dates", []),
            "priority": cfg.get("priority", 999),
        }
    return sources


def get_db_instruments(source_name):
    """Load instrument list for a source from the SQLite registry.

    Returns:
        List of instrument name strings.
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT DISTINCT instrument FROM source_instruments WHERE source_name = ?",
        (source_name,),
    )
    instruments = [row[0] for row in cursor.fetchall()]
    conn.close()
    return instruments


def get_backfill_config():
    """Load backfill configuration from YAML.

    Returns:
        Dict with 'assets' and 'concurrency_limit' keys.
    """
    config = load_yaml_config()
    return config.get("backfill", {})


def get_cost_config():
    """Load cost optimization configuration from YAML.

    Returns:
        Dict with 'source_costs' and 'affinity_groups' keys.
    """
    with open(COST_CONFIG_PATH) as f:
        return yaml.safe_load(f)
