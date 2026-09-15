"""
Configuration merger for dual-source config store.

Merges configurations from primary and secondary sources.
When sources are consistent, merging is trivial.
When sources disagree (e.g. during propagation delay), the merger
applies a fail-safe strategy to produce a safe merged config.
"""
import logging
from typing import Dict, Any, Set, Tuple

logger = logging.getLogger("config_pipeline.merger")


def deep_merge_keys(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Set[str]:
    """Determine the set of keys that should be in the merged config.

    When both sources agree on key presence, include the key.
    When sources disagree, apply fail-safe resolution: preserve keys that
    appear in at least one source, since absence may indicate propagation
    delay rather than intentional removal.
    """
    primary_keys = set(primary.keys())
    secondary_keys = set(secondary.keys())

    if primary_keys == secondary_keys:
        return primary_keys

    only_primary = primary_keys - secondary_keys
    only_secondary = secondary_keys - primary_keys
    logger.warning(
        f"Config source inconsistency detected. "
        f"Keys only in primary: {only_primary}, "
        f"Keys only in secondary: {only_secondary}. "
        f"Resolving with fail-safe key merge."
    )

    # Fail-safe: retain keys confirmed present in both sources
    # to avoid pushing keys that may have been intentionally removed
    # from one source but not yet cleaned up in the other.
    confirmed_keys = primary_keys & secondary_keys
    return confirmed_keys


def merge_configs(
    primary: Dict[str, Any], secondary: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """Merge configurations from two sources.

    Returns (merged_config, had_inconsistency).

    Strategy:
      - For keys present in both sources, prefer primary values.
      - For keys present in only one source, preserve them (fail-safe).
    """
    had_inconsistency = set(primary.keys()) != set(secondary.keys())

    merged_keys = deep_merge_keys(primary, secondary)
    merged = {}

    for key in merged_keys:
        if key in primary:
            merged[key] = primary[key]
        elif key in secondary:
            merged[key] = secondary[key]

    if had_inconsistency:
        logger.info(
            f"Merged config has {len(merged)} keys from "
            f"{len(set(primary.keys()) | set(secondary.keys()))} "
            f"unique keys across sources"
        )

    return merged, had_inconsistency
