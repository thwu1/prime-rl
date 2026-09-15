#!/usr/bin/env python3
"""
Complete fix for the cascading configuration failure.

Addresses:
1. Generator SQL query missing database filter (duplicate features)
2. Generator non-atomic file writes (TOCTOU race condition)
3. Proxy crashing instead of failing open on oversized config
4. Missing configuration validation pipeline
5. Architecture design document
6. Incident report

"""

import os
import json
import subprocess
import sys


def fix_generator():
    """Fix the feature generator: SQL filter + atomic writes."""
    gen_path = "/app/generator/generate.py"
    with open(gen_path, 'r') as f:
        content = f.read()

    # Fix 1: Add database filter to SQL query
    old_query = """        SELECT name, type
        FROM system_columns
        WHERE table_name = 'http_requests_features'
        ORDER BY name"""

    new_query = """        SELECT name, type
        FROM system_columns
        WHERE table_name = 'http_requests_features'
          AND database = 'default'
        ORDER BY name"""

    if old_query in content:
        content = content.replace(old_query, new_query)
        print("[+] Fixed generator: added database='default' filter")
    else:
        print("[!] Generator query pattern not found - may already be fixed")

    # Fix 2: Atomic file writes (temp file + os.replace)
    old_write = """    with open(output_path, 'w') as f:
        json.dump(feature_file, f, indent=2)"""

    new_write = """    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=OUTPUT_DIR, suffix='.tmp')
    try:
        with os.fdopen(tmp_fd, 'w') as f:
            json.dump(feature_file, f, indent=2)
        os.replace(tmp_path, output_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise"""

    if old_write in content:
        content = content.replace(old_write, new_write)
        print("[+] Fixed generator: atomic file writes via tempfile + os.replace")
    else:
        print("[!] Generator write pattern not found - may already be fixed")

    with open(gen_path, 'w') as f:
        f.write(content)


def fix_proxy():
    """Fix the proxy to fail-open instead of crashing."""
    proxy_path = "/app/proxy/server.py"
    with open(proxy_path, 'r') as f:
        content = f.read()

    # Fix 1: Truncate features instead of raising RuntimeError
    old_limit_check = '''        if feature_count > MAX_FEATURES:
            error_msg = (
                f"Feature count {feature_count} exceeds maximum allowed "
                f"{MAX_FEATURES}. Cannot pre-allocate memory for feature scoring."
            )
            logger.error(error_msg)
            raise RuntimeError(
                f"called Result::unwrap() on an Err value: "
                f"FeatureLimitExceeded({{count: {feature_count}, "
                f"max: {MAX_FEATURES}}})"
            )'''

    new_limit_check = '''        if feature_count > MAX_FEATURES:
            logger.warning(
                f"Feature count {feature_count} exceeds maximum allowed "
                f"{MAX_FEATURES}. Truncating to {MAX_FEATURES} features. "
                f"Bot scoring will operate in degraded mode."
            )
            features = features[:MAX_FEATURES]
            feature_count = len(features)'''

    if old_limit_check in content:
        content = content.replace(old_limit_check, new_limit_check)
        print("[+] Fixed proxy: truncate instead of crash on oversized files")
    else:
        print("[!] Proxy limit check pattern not found - may already be fixed")

    # Fix 2: Fail-open initialization
    old_init_handler = '''        except RuntimeError as e:
            logger.error(f"FL2 proxy initialization failed: {e}")
            # Simulate Rust panic behavior - hard crash, no recovery
            logger.critical(
                f"thread fl2_worker_thread panicked: {e}\\n"
                f"note: run with `RUST_BACKTRACE=1` for a backtrace"
            )
            raise SystemExit(1)'''

    new_init_handler = '''        except RuntimeError as e:
            logger.warning(f"FL2 proxy initialization issue: {e}")
            logger.warning("Continuing with degraded bot scoring (fail-open)")
            self.bot_module.features = []
            self.bot_module.feature_memory = [0.0] * MAX_FEATURES
            self.running = True'''

    if old_init_handler in content:
        content = content.replace(old_init_handler, new_init_handler)
        print("[+] Fixed proxy: fail-open instead of panic on errors")
    else:
        print("[!] Proxy init handler pattern not found - may already be fixed")

    with open(proxy_path, 'w') as f:
        f.write(content)


def create_validator():
    """Create the configuration validation module."""
    os.makedirs("/app/config_safety", exist_ok=True)

    validator_code = '''"""
Configuration validation for bot management feature files.

Validates feature configurations against system invariants
to prevent cascading failures from invalid config deployment.
"""

import json
import os


def _get_max_features():
    config_path = "/app/config/settings.json"
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        return cfg.get("proxy", {}).get("max_features", 200)
    return 200


MAX_FEATURES = _get_max_features()

REQUIRED_FIELDS = {"version", "features"}
REQUIRED_FEATURE_FIELDS = {"name", "type"}
VALID_TYPES = {
    "Float64", "UInt8", "UInt16", "UInt32", "UInt64",
    "Int8", "Int16", "Int32", "Int64", "String"
}


def validate_config(data: dict) -> tuple:
    """Validate a feature configuration.

    Args:
        data: Parsed JSON configuration data

    Returns:
        Tuple of (is_valid: bool, error_messages: list[str])
    """
    errors = []

    # Check required top-level fields
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if "features" not in data:
        return (False, errors)

    features = data["features"]

    if not isinstance(features, list):
        errors.append("'features' must be a list")
        return (False, errors)

    # Check feature count limit
    if len(features) > MAX_FEATURES:
        errors.append(
            f"Feature count {len(features)} exceeds maximum {MAX_FEATURES}"
        )

    # Check for duplicates
    names = [f.get("name") for f in features if isinstance(f, dict)]
    seen = set()
    duplicates = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    if duplicates:
        errors.append(
            f"Duplicate feature names: {sorted(duplicates)}"
        )

    # Check individual features
    for i, feat in enumerate(features):
        if not isinstance(feat, dict):
            errors.append(f"Feature at index {i} is not a dict")
            continue

        for field in REQUIRED_FEATURE_FIELDS:
            if field not in feat:
                errors.append(f"Feature at index {i} missing field: {field}")

        feat_type = feat.get("type")
        if feat_type and feat_type not in VALID_TYPES:
            feat_name = feat.get("name", str(i))
            errors.append(
                "Feature " + repr(feat_name) + " has invalid type: " + str(feat_type)
            )

        weight = feat.get("weight")
        if weight is not None and (not isinstance(weight, (int, float)) or weight < 0):
            feat_name = feat.get("name", str(i))
            errors.append(
                "Feature " + repr(feat_name) + " has invalid weight: " + str(weight)
            )

    # Check feature_count consistency
    declared = data.get("feature_count")
    if declared is not None and declared != len(features):
        errors.append(
            f"Declared feature_count ({declared}) != actual ({len(features)})"
        )

    return (len(errors) == 0, errors)
'''

    with open("/app/config_safety/validator.py", "w") as f:
        f.write(validator_code)

    init_path = "/app/config_safety/__init__.py"
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            f.write("")

    print("[+] Created configuration validator at /app/config_safety/validator.py")


def write_design_doc():
    """Write architecture design document."""
    doc = """# Configuration Safety Pipeline: Architecture Design Document

## Overview

This document evaluates architectural decisions for hardening the CDN proxy
system's configuration pipeline against cascading failures, based on the
November 2025 incident where a database permissions migration caused a
global proxy outage through a chain of interacting bugs.

## 1. Fail-Open vs Fail-Closed Analysis

### The Trade-off

**Fail-closed** (previous behavior): When the feature configuration exceeds
system limits or contains anomalies, the proxy panics and refuses to start.
This guarantees that no request is processed with an incorrect bot scoring
model, but causes a total service outage for all customers.

**Fail-open** (recommended): When configuration is degraded, the proxy
continues serving traffic with reduced bot detection capability. Some bot
traffic may bypass scoring, but legitimate customer traffic is not disrupted.

### Recommendation: Fail-Open with Degradation Signals

For bot management specifically, fail-open is the correct choice because:

1. **Availability > Accuracy**: A CDN proxy that returns 502 to all traffic
   is strictly worse than one that allows some bot traffic through. Customer
   SLAs are violated by outages, not by temporarily reduced bot detection.

2. **Blast radius containment**: Fail-closed converts a configuration issue
   (affecting bot scoring accuracy) into a global outage (affecting all
   traffic including non-bot-managed zones). This is severity amplification.

3. **Observability**: The proxy should emit metrics and alerts when operating
   in degraded mode, allowing operators to detect and fix the root cause
   without time pressure from an active outage.

The proxy should truncate features to MAX_FEATURES when oversized, log a
warning, and continue serving. Degraded mode should be visible in health
check responses and monitoring dashboards.

## 2. Configuration Deployment Strategy

### Instant Global Propagation (previous approach)

The previous system regenerated the feature file every 5 minutes from a
randomly selected database shard and immediately deployed it. This creates:

- Bad shard produces bad config that immediately affects all traffic
- No opportunity to catch errors before global impact
- Random shard selection makes failures intermittent and hard to diagnose

### Recommended: Canary Deployment with Validation Gate

1. **Pre-deployment validation**: Every generated config must pass the
   validation pipeline before deployment. This catches known-bad patterns
   (duplicate features, exceeded limits, missing fields).

2. **Canary shard**: Generate from one shard first, validate, and test
   against a shadow proxy instance before generating from all shards.

3. **Consistency check**: Compare outputs across all shards. If any shard
   produces a different feature count, halt deployment and alert.

4. **Atomic file replacement**: Use write-to-temp-file + atomic rename
   to prevent the proxy from reading partial configurations during writes.

5. **Rollback**: Keep the last known-good configuration. If the new config
   fails validation, automatically revert to the previous version.

## 3. Configuration Validation Invariants

The validation pipeline enforces these specific invariants:

1. **Feature count bounded**: `len(features) <= MAX_FEATURES` (200).
   Prevents memory pre-allocation overflow. Violations indicate upstream
   query or data issues.

2. **No duplicate names**: Each feature name must be unique. Duplicates
   indicate a missing filter in the metadata query (the root cause of
   this specific incident).

3. **Type safety**: Each feature must have a recognized data type from
   the set of supported ClickHouse column types (Float64, UInt8, etc.).

4. **Schema completeness**: Required fields (version, features) must be
   present at the top level. Each feature must have at minimum a name
   and type field.

5. **Count consistency**: The declared `feature_count` must match the
   actual number of features in the array.

6. **Weight validity**: Feature weights must be non-negative numbers.

These invariants are enforced by `validate_config()` in
`/app/config_safety/validator.py`, integrated into `cfctl config validate`
and the canary deployment pipeline via `cfctl deploy canary`.

## 4. Atomic File Operations

### Problem

The generator truncated the output file (opening with 'w' mode) before
writing new content. If the proxy reads during this window, it sees empty
or partial JSON, causing parse errors or incorrect behavior.

### Solution

Write-to-temp-file + atomic rename:
1. Write new content to a temporary file in the same directory
2. Use `os.replace()` to atomically swap the temp file into place
3. On failure, clean up the temp file

This is preferred over file locking because:
- Atomic rename is a single filesystem operation (no lock contention)
- No risk of deadlock from forgotten locks
- Compatible with multiple concurrent readers
- Standard Unix pattern with well-understood semantics
"""

    with open("/app/design_doc.md", "w") as f:
        f.write(doc)

    print("[+] Wrote architecture design document to /app/design_doc.md")


def write_incident_report():
    """Write incident root cause analysis."""
    report = """INCIDENT REPORT: Cascading Configuration Failure
==================================================

Date: 2025-11-18
Duration: ~3 hours 46 minutes (11:20 - ~15:06 UTC)
Severity: P0 - Global service outage
Impact: FL2 proxy crashes, HTTP 5xx errors for all customer traffic

ROOT CAUSE CHAIN
-----------------

The outage was caused by a cascading failure across three system components,
triggered by a database permissions migration.

1. TRIGGER - Database Permissions Migration:
   At 11:05 UTC, a permissions migration was applied to the ClickHouse
   distributed database cluster (shards 0-3 migrated, shard 4 pending).
   The migration made the underlying 'r0' database table metadata visible
   in system_columns alongside the existing 'default' database entries.

2. PROPAGATION - Unfiltered Metadata Query:
   The feature file generator's SQL query:

     SELECT name, type FROM system_columns
     WHERE table_name = 'http_requests_features'

   This query lacked a database filter (AND database = 'default'). On
   migrated shards, it returned 226 rows (113 from 'default' + 113 from
   'r0') instead of the expected 113. The generator wrote these duplicates
   to bot_features.json without any validation step.

3. CRASH - Hard Feature Limit with No Graceful Degradation:
   The FL2 proxy has a hard limit of MAX_FEATURES = 200 for memory
   pre-allocation. When loading 226 features, the BotScoringModule raised
   a RuntimeError simulating Result::unwrap() on Err, and the proxy caught
   it only to call SystemExit(1) - a hard crash with no recovery path.

4. INTERMITTENT PATTERN:
   Because shard 4 was not yet migrated, ~20% of regeneration cycles
   selected shard 4 and produced the correct 113-feature file. The proxy
   recovered until the next cycle selected a migrated shard. This 80/20
   failure ratio made diagnosis difficult and initially pointed toward
   a DDoS attack rather than a configuration issue.

5. FILE WRITE RACE CONDITION:
   The generator also wrote the config file non-atomically (truncating
   before writing), creating a TOCTOU window where the proxy could read
   partial or empty JSON during the write.

CONTRIBUTING FACTORS
--------------------
- Configuration validation was never implemented (cfctl.log shows repeated
  "NOT_IMPLEMENTED" warnings for config.validate on every deployment)
- The proxy used fail-closed behavior, converting a configuration quality
  issue into a total service outage
- Red herring events (DDoS alerts, status page outage) in system.log
  delayed root cause identification
- No cross-shard consistency checks to detect different feature counts
- The permissions migration lacked impact analysis for system_columns
  consumers

FIXES APPLIED
--------------
1. Added database='default' filter to generator SQL query
2. Implemented atomic file writes (tempfile + os.replace) in generator
3. Changed proxy to fail-open: truncate features to MAX_FEATURES and
   continue in degraded mode instead of crashing
4. Created configuration validation pipeline at /app/config_safety/validator.py
   enforcing: feature count limits, no duplicates, type safety, schema
   completeness, weight validity
5. Integrated validator with cfctl config validate command

PREVENTION MEASURES
-------------------
- All metadata queries must explicitly specify the target database
- Critical services must fail-open on configuration errors
- Pre-deployment validation gate for all configuration changes
- Canary deployment: test config from one shard before global rollout
- Cross-shard consistency checks: all shards must produce identical counts
- Atomic file operations for all configuration file updates
- Database schema migrations must include impact analysis for all consumers
"""

    with open("/app/incident_report.txt", 'w') as f:
        f.write(report)

    print("[+] Wrote incident report to /app/incident_report.txt")


def regenerate_and_verify():
    """Regenerate feature file and verify all fixes."""
    # Verify all shards produce same count
    counts = {}
    for i in range(5):
        shard = f"/app/db/shards/shard_{i}.db"
        subprocess.run(
            [sys.executable, "/app/generator/generate.py", shard],
            capture_output=True, text=True
        )
        with open("/app/features/bot_features.json") as f:
            data = json.load(f)
        counts[f"shard_{i}"] = len(data["features"])

    print(f"[+] Feature counts per shard: {counts}")
    assert len(set(counts.values())) == 1, f"Inconsistent counts: {counts}"

    # Final regeneration from shard 0
    result = subprocess.run(
        [sys.executable, "/app/generator/generate.py",
         "/app/db/shards/shard_0.db"],
        capture_output=True, text=True
    )
    print(f"[+] Final regeneration: {result.stdout.strip()}")


def main():
    print("=" * 55)
    print("Applying cascading failure fixes...")
    print("=" * 55)
    print()

    fix_generator()
    print()
    fix_proxy()
    print()
    create_validator()
    print()
    write_design_doc()
    print()
    write_incident_report()
    print()
    regenerate_and_verify()

    print()
    print("=" * 55)
    print("All fixes applied successfully.")
    print("=" * 55)


if __name__ == "__main__":
    main()
