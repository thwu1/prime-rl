# Post-Incident Review: BYOIP Mass Prefix Withdrawal
## Date: 2025-11-18 | Severity: P0 | Duration: ~2 hours

### Summary

A cascading failure in the CDN configuration pipeline resulted in the withdrawal of all 50 customer BYOIP prefixes from global routing tables. Only 5 prefixes were legitimately queued for deletion. The cascade involved multiple independent code changes that interacted in unexpected ways.

### Timeline

- **10:30 UTC** — Recent code changes deployed to production
- **11:05 UTC** — Database migration 002 applied to production ClickHouse cluster, exposing replica schema metadata to user queries
- **11:20 UTC** — Pipeline run: config generator retrieves 224 features (expected ~112). Config loader panics on oversized feature file.
- **11:25 UTC** — Pipeline retry: intermittently retrieves correct feature count (load balancer routes to pre-migration node). Pipeline proceeds through all stages. Cleanup task queries pending prefixes — receives all 50 instead of only 5 pending — withdraws entire fleet. All service bindings deleted.
- **11:28 UTC** — Subsequent pipeline run crashes again on 224 features
- **11:35 UTC** — Customer reports total loss of BYOIP connectivity
- **12:00 UTC** — Incident declared. Manual investigation begins.
- **14:00 UTC** — Root causes identified. This review drafted.

### Impact

- 45 customer BYOIP prefixes incorrectly de-advertised from global routing tables
- All 50 prefix service bindings deleted from the operational database
- Complete BYOIP service disruption for approximately 2 hours
- Multiple customer escalations and SLA violations

### Root Cause Analysis

Multiple independent code changes contributed to the cascade. The git history at `/app/` contains the relevant commits made shortly before the incident. Cross-reference commit timestamps with the log artifacts in `/app/logs/` to reconstruct the full chain of causation.

The failure required all three bugs to interact: one amplified the data volume, one removed a safety net, and one misdirected the cleanup scope. Any single bug in isolation would not have caused the full outage.

### Remediation Action Items

#### R1: Identify and fix all root-cause bugs

All code defects that contributed to the cascading failure must be corrected in the pipeline source. Use the git history and log correlation to ensure no contributing factor is missed.

#### R2: Implement batch safety validation module

Create `/app/circuit_breaker.py` exporting the following functions:

**`validate_cleanup_batch(prefix_ids_to_withdraw, total_active_prefixes)`** → `(bool, str)`
- Returns a tuple of (is_safe, human-readable reason)
- Reject any batch that would withdraw **more than 10%** of active prefixes
- Exactly 10% is within the safety threshold (not "exceeding")
- Edge case: if `total_active_prefixes` is 0 or negative, reject any non-empty batch
- An empty batch is always safe

**`validate_feature_count(count, max_limit)`** → `(bool, str)`
- Returns a tuple of (is_safe, human-readable reason)
- Reject when `count` **strictly exceeds** `max_limit` (count equal to max_limit is acceptable)
- When `count` exceeds **80%** of `max_limit`, include the word "warning" (case-insensitive) in the reason string

All validation decisions must be logged to `/app/logs/circuit_breaker.log`.

#### R3: Integrate safety module into pipeline

Gate both the prefix cleanup process and the feature loading pipeline through the safety validation module before allowing operations to proceed. Neither the cleanup task nor the config pipeline should execute unchecked operations.

#### R4: Database restoration

Restore the database to its correct pre-incident operational state. All non-pending prefixes must be re-advertised and their service bindings recreated with correct service types and valid JSON configuration matching the original data model.
