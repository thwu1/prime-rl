#!/usr/bin/env python3
"""
Set up the task environment:
1. Compress and rotate log files (simulating logrotate)
2. Create git history showing the development timeline and bug introductions
"""
import subprocess
import os
import gzip

os.chdir('/app')

# ════════════════════════════════════════════════════════════
# Part 1: Log rotation and compression
# ════════════════════════════════════════════════════════════

# Split pipeline.log: keep only the last crash in current log,
# compress the full history (including the critical 50-prefix withdrawal)
with open('logs/pipeline.log') as f:
    full_log = f.read()

marker = '2025-11-18 11:30:01'
idx = full_log.index(marker)
rotated_portion = full_log[:idx]
current_portion = full_log[idx:]

with gzip.open('logs/pipeline.log.1.gz', 'wt') as f:
    f.write(rotated_portion)
with open('logs/pipeline.log', 'w') as f:
    f.write(current_portion)

# Compress crash report
with open('logs/crash_report.log') as f:
    crash_content = f.read()
with gzip.open('logs/crash_report.log.gz', 'wt') as f:
    f.write(crash_content)
os.remove('logs/crash_report.log')

print("Logs rotated and compressed")

# ════════════════════════════════════════════════════════════
# Part 2: Git history
# ════════════════════════════════════════════════════════════

def git(*args, env=None):
    subprocess.run(
        ['git'] + list(args),
        check=True, capture_output=True,
        env=env or os.environ,
    )

def commit(msg, date):
    env = {**os.environ, 'GIT_AUTHOR_DATE': date, 'GIT_COMMITTER_DATE': date}
    git('add', '-A')
    git('commit', '-m', msg, env=env)

git('init')
git('config', 'user.email', 'pipeline-team@cdn.internal')
git('config', 'user.name', 'CDN Pipeline Team')

# Create .gitignore (logs and runtime artifacts excluded from VCS)
with open('.gitignore', 'w') as f:
    f.write('logs/\nconfigs/\ndb/features.db\n__pycache__/\n*.pyc\n')

# ── Save original (buggy) file contents ──
with open('api_server.py') as f:
    api_original = f.read()
with open('config_loader.py') as f:
    loader_original = f.read()

# Temporarily move post-incident review (added in final commit)
os.rename('docs/post_incident_review.md', '/tmp/pir.md')

# ── Create clean api_server.py (reverse all bugs) ──
api_clean = api_original

# Reverse Bug 1: restore schema_name filter and simplify comment
api_clean = api_clean.replace(
    '    # Retrieve feature columns for the specified table.\n'
    '    # After migration 002_expose_replica_access, users can see\n'
    '    # metadata from both default and r0 schemas for improved\n'
    '    # distributed query security and reliability.\n',
    '    # Retrieve feature columns for the specified table\n'
    '    # from the default schema.\n'
)
api_clean = api_clean.replace(
    "           WHERE table_name = ?\n           ORDER BY name",
    "           WHERE table_name = ? AND schema_name = 'default'\n           ORDER BY name"
)

# Reverse Bug 2: use presence check instead of truthiness
api_clean = api_clean.replace(
    "    pending_delete_filter = request.args.get('pending_delete')\n"
    "    if pending_delete_filter:",
    "    if 'pending_delete' in request.args:"
)

# ── Create clean config_loader.py (reverse crash to graceful handling) ──
crash_block = (
    '    # Validate against preallocated limit\n'
    '    # This limit exists for memory preallocation performance optimization\n'
    '    if feature_count > MAX_FEATURES:\n'
    '        # Equivalent to Rust: Result::unwrap() on Err\n'
    '        raise RuntimeError(\n'
    '            f"Feature count {feature_count} exceeds maximum allocation "\n'
    '            f"limit of {MAX_FEATURES}. Aborting to prevent unbounded "\n'
    '            f"memory consumption."\n'
    '        )'
)

graceful_block = (
    '    # Deduplicate features by name (defense against upstream duplicates)\n'
    '    seen = set()\n'
    '    unique = []\n'
    '    for feat in features:\n'
    '        fname = feat.get(\'name\', \'\')\n'
    '        if fname not in seen:\n'
    '            seen.add(fname)\n'
    '            unique.append(feat)\n'
    '    if len(unique) < feature_count:\n'
    '        logger.warning("Deduplicated: %d -> %d features", feature_count, len(unique))\n'
    '    features = unique\n'
    '    feature_count = len(features)\n'
    '\n'
    '    # Graceful degradation: truncate if over preallocated limit\n'
    '    if feature_count > MAX_FEATURES:\n'
    '        logger.warning("Truncating: %d -> %d features", feature_count, MAX_FEATURES)\n'
    '        features = features[:MAX_FEATURES]\n'
    '        feature_count = MAX_FEATURES'
)

loader_clean = loader_original.replace(crash_block, graceful_block)
assert loader_clean != loader_original, "Failed to create clean config_loader.py"

# ════════════════════════════════════════════════════════════
# Commit 1: Clean initial implementation
# ════════════════════════════════════════════════════════════
with open('api_server.py', 'w') as f:
    f.write(api_clean)
with open('config_loader.py', 'w') as f:
    f.write(loader_clean)
commit("feat: initial CDN configuration pipeline", "2024-03-15T10:00:00+00:00")

# ════════════════════════════════════════════════════════════
# Commit 2: Bug 1 — Remove schema filter for migration 002
# ════════════════════════════════════════════════════════════
api_v1 = api_clean.replace(
    '    # Retrieve feature columns for the specified table\n'
    '    # from the default schema.\n',
    '    # Retrieve feature columns for the specified table.\n'
    '    # After migration 002_expose_replica_access, users can see\n'
    '    # metadata from both default and r0 schemas for improved\n'
    '    # distributed query security and reliability.\n'
)
api_v1 = api_v1.replace(
    "           WHERE table_name = ? AND schema_name = 'default'\n           ORDER BY name",
    "           WHERE table_name = ?\n           ORDER BY name"
)
with open('api_server.py', 'w') as f:
    f.write(api_v1)
commit(
    "chore: apply migration 002 - expose r0 schema for distributed query security",
    "2025-11-18T10:30:00+00:00",
)

# ════════════════════════════════════════════════════════════
# Commit 3: Bug 2 — Change pending_delete to truthiness check
# ════════════════════════════════════════════════════════════
api_v2 = api_v1.replace(
    "    if 'pending_delete' in request.args:",
    "    pending_delete_filter = request.args.get('pending_delete')\n"
    "    if pending_delete_filter:"
)
with open('api_server.py', 'w') as f:
    f.write(api_v2)
commit(
    "refactor: use request.args.get for cleaner parameter handling",
    "2025-11-18T10:45:00+00:00",
)

# ════════════════════════════════════════════════════════════
# Commit 4: Bug 3 — Replace graceful degradation with crash
# ════════════════════════════════════════════════════════════
# Verify round-trip correctness for api_server.py
assert api_v2 == api_original, "Round-trip mismatch in api_server.py"

# Restore original (buggy) files — api_server.py already matches,
# config_loader.py needs to be reverted to the crash version
with open('api_server.py', 'w') as f:
    f.write(api_original)
with open('config_loader.py', 'w') as f:
    f.write(loader_original)
commit(
    "perf: enforce strict memory allocation limits in config loader",
    "2025-11-18T11:00:00+00:00",
)

# ════════════════════════════════════════════════════════════
# Commit 5: Post-incident review document
# ════════════════════════════════════════════════════════════
os.rename('/tmp/pir.md', 'docs/post_incident_review.md')
commit(
    "docs: post-incident review for 2025-11-18 BYOIP mass withdrawal",
    "2025-11-18T18:00:00+00:00",
)

print("Git history created with 5 commits")
