#!/usr/bin/env python3
"""
Complete incident response solution for CDN configuration pipeline.

Performs:
1. Fix three root cause bugs (SQL filter, query param, crash handling)
2. Restore database to pre-incident state
3. Create circuit breaker module
4. Integrate circuit breaker into pipeline
"""

import json
import sqlite3
import os


# ────────────────────────────────────────────────────────────
# Bug Fixes
# ────────────────────────────────────────────────────────────

def fix_api_server():
    """Fix bugs 1 (SQL schema filter) and 2 (query param check)."""
    with open('/app/api_server.py', 'r') as f:
        content = f.read()

    # Bug 1: The SQL query retrieves features from ALL schemas
    # after migration 002 exposed r0. Add schema_name filter.
    content = content.replace(
        "WHERE table_name = ?",
        "WHERE table_name = ? AND schema_name = 'default'"
    )

    # Bug 2: pending_delete check uses truthiness — empty string
    # from ?pending_delete (no value) is falsy. Check presence instead.
    content = content.replace(
        "    pending_delete_filter = request.args.get('pending_delete')\n"
        "    if pending_delete_filter:",
        "    if 'pending_delete' in request.args:"
    )

    with open('/app/api_server.py', 'w') as f:
        f.write(content)
    print("[fix] api_server.py: schema filter + parameter presence check")


def fix_config_loader():
    """Fix bug 3: replace crash with deduplication + truncation."""
    with open('/app/config_loader.py', 'r') as f:
        content = f.read()

    old_block = (
        "    # Validate against preallocated limit\n"
        "    # This limit exists for memory preallocation performance "
        "optimization\n"
        "    if feature_count > MAX_FEATURES:\n"
        "        # Equivalent to Rust: Result::unwrap() on Err\n"
        "        raise RuntimeError(\n"
        "            f\"Feature count {feature_count} exceeds maximum "
        "allocation \"\n"
        "            f\"limit of {MAX_FEATURES}. Aborting to prevent "
        "unbounded \"\n"
        "            f\"memory consumption.\"\n"
        "        )"
    )

    new_block = (
        "    # Deduplicate features by name (defense against duplicate "
        "schema entries)\n"
        "    seen_names = set()\n"
        "    unique_features = []\n"
        "    for feat in features:\n"
        "        fname = feat.get('name', '')\n"
        "        if fname not in seen_names:\n"
        "            seen_names.add(fname)\n"
        "            unique_features.append(feat)\n"
        "    if len(unique_features) < feature_count:\n"
        "        logger.warning(\n"
        "            \"Deduplicated features: %d -> %d\",\n"
        "            feature_count, len(unique_features),\n"
        "        )\n"
        "    features = unique_features\n"
        "    feature_count = len(features)\n"
        "\n"
        "    # Graceful degradation: truncate if still over limit\n"
        "    if feature_count > MAX_FEATURES:\n"
        "        logger.warning(\n"
        "            \"Feature count %d exceeds limit %d, truncating\",\n"
        "            feature_count, MAX_FEATURES,\n"
        "        )\n"
        "        features = features[:MAX_FEATURES]\n"
        "        feature_count = MAX_FEATURES"
    )

    content = content.replace(old_block, new_block)

    with open('/app/config_loader.py', 'w') as f:
        f.write(content)
    print("[fix] config_loader.py: deduplication + truncation")


# ────────────────────────────────────────────────────────────
# Database Restoration
# ────────────────────────────────────────────────────────────

def restore_database():
    """Restore database to pre-incident operational state."""
    conn = sqlite3.connect('/app/db/features.db')

    # Re-advertise ALL prefixes (pre-incident state: all were advertised)
    conn.execute("UPDATE prefixes SET advertised = 1")

    # Recreate service bindings for all prefixes
    # (the buggy cleanup deleted all of them via withdraw_prefix)
    prefixes = conn.execute(
        "SELECT id, service_binding FROM prefixes"
    ).fetchall()

    for prefix_id, service_type in prefixes:
        exists = conn.execute(
            "SELECT COUNT(*) FROM service_bindings WHERE prefix_id = ?",
            (prefix_id,)
        ).fetchone()[0]
        if not exists and service_type:
            conn.execute(
                "INSERT INTO service_bindings "
                "(prefix_id, service_type, config) VALUES (?, ?, ?)",
                (prefix_id, service_type,
                 json.dumps({"region": "global", "priority": 100}))
            )

    conn.commit()

    advertised = conn.execute(
        "SELECT COUNT(*) FROM prefixes WHERE advertised = 1"
    ).fetchone()[0]
    bindings = conn.execute(
        "SELECT COUNT(*) FROM service_bindings"
    ).fetchone()[0]
    conn.close()

    print(f"[restore] Database: {advertised} prefixes advertised, "
          f"{bindings} service bindings")


# ────────────────────────────────────────────────────────────
# Circuit Breaker Creation
# ────────────────────────────────────────────────────────────

def create_circuit_breaker():
    """Create circuit breaker module at /app/circuit_breaker.py."""
    code = '''\
#!/usr/bin/env python3
"""
Circuit breaker for CDN configuration pipeline.

Provides safety validation for cleanup batch operations and feature
count limits to prevent cascading failures from causing widespread
prefix withdrawal or config loader crashes.
"""

import logging
import os

os.makedirs('/app/logs', exist_ok=True)

logger = logging.getLogger('circuit_breaker')
if not logger.handlers:
    _handler = logging.FileHandler('/app/logs/circuit_breaker.log')
    _handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def validate_cleanup_batch(prefix_ids_to_withdraw, total_active_prefixes):
    """Validate that a cleanup batch will not cause excessive damage.

    Rejects batches that would withdraw more than 10% of active prefixes.

    Args:
        prefix_ids_to_withdraw: List of prefix IDs to withdraw.
        total_active_prefixes: Total number of currently active prefixes.

    Returns:
        Tuple of (safe: bool, reason: str).
    """
    batch_size = len(prefix_ids_to_withdraw)

    if batch_size == 0:
        reason = "Empty batch — nothing to withdraw"
        logger.info("PASS: %s", reason)
        return True, reason

    if total_active_prefixes <= 0:
        reason = (
            f"Rejecting withdrawal of {batch_size} prefixes: "
            f"no active prefixes exist"
        )
        logger.warning("REJECT: %s", reason)
        return False, reason

    ratio = batch_size / total_active_prefixes
    pct = ratio * 100

    if ratio > 0.10:
        reason = (
            f"Batch of {batch_size}/{total_active_prefixes} "
            f"({pct:.1f}%) exceeds 10% safety threshold"
        )
        logger.warning("REJECT: %s", reason)
        return False, reason

    reason = (
        f"Batch of {batch_size}/{total_active_prefixes} "
        f"({pct:.1f}%) within safety threshold"
    )
    logger.info("PASS: %s", reason)
    return True, reason


def validate_feature_count(count, max_limit):
    """Validate feature count against operational limits.

    Rejects counts exceeding max_limit. Includes a warning in the
    reason when count exceeds 80% of max_limit.

    Args:
        count: Current feature count.
        max_limit: Maximum allowed feature count.

    Returns:
        Tuple of (safe: bool, reason: str).
    """
    if count > max_limit:
        reason = (
            f"Feature count {count} exceeds limit of {max_limit}"
        )
        logger.warning("REJECT: %s", reason)
        return False, reason

    if max_limit > 0:
        ratio = count / max_limit
        pct = ratio * 100
    else:
        ratio = 0
        pct = 0

    if ratio > 0.80:
        reason = (
            f"Warning: feature count {count}/{max_limit} ({pct:.1f}%) "
            f"approaching limit — monitor closely"
        )
        logger.info("PASS with warning: %s", reason)
        return True, reason

    reason = (
        f"Feature count {count}/{max_limit} ({pct:.1f}%) "
        f"within normal range"
    )
    logger.info("PASS: %s", reason)
    return True, reason
'''

    with open('/app/circuit_breaker.py', 'w') as f:
        f.write(code)
    print("[create] circuit_breaker.py")


# ────────────────────────────────────────────────────────────
# Circuit Breaker Integration
# ────────────────────────────────────────────────────────────

def integrate_into_pipeline():
    """Integrate circuit breaker into run_pipeline.py and cleanup_task.py."""

    # --- run_pipeline.py: add feature count validation after step 2 ---
    with open('/app/run_pipeline.py', 'r') as f:
        content = f.read()

    old_step2_done = (
        '        logger.info("Step 2 complete: %d features loaded", '
        'len(features))'
    )
    new_step2_done = (
        '        logger.info("Step 2 complete: %d features loaded", '
        'len(features))\n'
        '\n'
        '        # Circuit breaker: validate feature count\n'
        '        from circuit_breaker import validate_feature_count\n'
        '        from config_loader import MAX_FEATURES\n'
        '        cb_safe, cb_reason = validate_feature_count(\n'
        '            len(features), MAX_FEATURES\n'
        '        )\n'
        '        logger.info("Feature validation: safe=%s reason=%s", '
        'cb_safe, cb_reason)\n'
        '        if not cb_safe:\n'
        '            logger.critical("Circuit breaker tripped: %s", '
        'cb_reason)\n'
        '            return False'
    )

    content = content.replace(old_step2_done, new_step2_done)

    with open('/app/run_pipeline.py', 'w') as f:
        f.write(content)

    # --- cleanup_task.py: add batch validation before withdrawal ---
    with open('/app/cleanup_task.py', 'r') as f:
        content = f.read()

    old_cleanup_section = (
        '    logger.info("Found %d prefixes to clean up", len(prefixes))\n'
        '\n'
        '    withdrawn = 0'
    )
    new_cleanup_section = (
        '    logger.info("Found %d prefixes to clean up", len(prefixes))\n'
        '\n'
        '    # Circuit breaker: validate batch size\n'
        '    from circuit_breaker import validate_cleanup_batch\n'
        '    resp_all = requests.get(f"{API_BASE}/api/prefixes")\n'
        '    resp_all.raise_for_status()\n'
        '    total_count = len(resp_all.json())\n'
        '    cb_safe, cb_reason = validate_cleanup_batch(\n'
        '        [p["id"] for p in prefixes], total_count\n'
        '    )\n'
        '    if not cb_safe:\n'
        '        logger.warning("Circuit breaker rejected: %s", cb_reason)\n'
        '        return 0, 0\n'
        '    logger.info("Circuit breaker approved: %s", cb_reason)\n'
        '\n'
        '    withdrawn = 0'
    )

    content = content.replace(old_cleanup_section, new_cleanup_section)

    with open('/app/cleanup_task.py', 'w') as f:
        f.write(content)

    print("[integrate] Circuit breaker wired into pipeline and cleanup")


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    fix_api_server()
    fix_config_loader()
    restore_database()
    create_circuit_breaker()
    integrate_into_pipeline()
    print("\nIncident response complete — all fixes applied.")
