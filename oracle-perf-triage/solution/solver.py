#!/usr/bin/env python3
"""
Oracle Performance Analysis Audit Solver

Queries SQLite database containing Oracle V$ performance view exports,
detects data anomalies, computes correct metrics, evaluates a prior
analyst's report, and produces corrected outputs.

"""

import sqlite3
import json
import os

DB_PATH = '/app/data/perfdata.db'
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row


def query(sql, params=None):
    return conn.execute(sql, params or ()).fetchall()


def query_one(sql, params=None):
    return conn.execute(sql, params or ()).fetchone()


def read_text(path):
    with open(path) as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# STEP 1: Detect data anomalies
# ══════════════════════════════════════════════════════════════════════════

data_anomalies = []

# Check for duplicate/inconsistent sysstat entries (trailing whitespace)
all_stats = query("SELECT name, value FROM sysstat")
seen_trimmed = {}
for row in all_stats:
    name_raw = row['name']
    trimmed = name_raw.strip()
    if trimmed in seen_trimmed:
        data_anomalies.append({
            'description': (
                f"Duplicate statistic entry for '{trimmed}' in sysstat table: "
                f"values {seen_trimmed[trimmed]} and {row['value']}. "
                f"One entry has trailing whitespace in the name column. "
                f"Using exact-match entry (no trailing space) as authoritative."
            )
        })
    else:
        seen_trimmed[trimmed] = row['value']

# Check for corrupted db_cache_advice rows (negative physical read factor)
bad_rows = query(
    "SELECT size_for_estimate, estd_physical_read_factor "
    "FROM db_cache_advice WHERE estd_physical_read_factor < 0"
)
for row in bad_rows:
    data_anomalies.append({
        'description': (
            f"Corrupted row in db_cache_advice: size_for_estimate="
            f"{row['size_for_estimate']} has negative "
            f"estd_physical_read_factor={row['estd_physical_read_factor']}. "
            f"A negative physical read factor is physically impossible and "
            f"indicates data corruption. This row is excluded from analysis."
        )
    })


# ══════════════════════════════════════════════════════════════════════════
# STEP 2: Compute correct performance metrics
# ══════════════════════════════════════════════════════════════════════════

def get_stat(name):
    """Get sysstat value using exact name match (avoids trailing-space dups)."""
    row = query_one("SELECT value FROM sysstat WHERE name = ?", (name,))
    return row['value'] if row else None


# Buffer cache hit ratio: 1 - physical_reads_cache / (consistent_gets_cache + db_block_gets_cache)
consistent_gets_cache = get_stat('consistent gets from cache')
db_block_gets_cache = get_stat('db block gets from cache')
physical_reads_cache = get_stat('physical reads cache')
buffer_cache_hit_ratio = 1.0 - (physical_reads_cache / (consistent_gets_cache + db_block_gets_cache))

# Library cache hit ratio: sum(pinhits) / sum(pins)
total_pins = query_one("SELECT SUM(pins) as s FROM librarycache")['s']
total_pinhits = query_one("SELECT SUM(pinhits) as s FROM librarycache")['s']
library_cache_hit_ratio = total_pinhits / total_pins

# SQL AREA specifics for findings
sql_area = query_one(
    "SELECT pins, pinhits, reloads FROM librarycache WHERE TRIM(namespace) = 'SQL AREA'"
)
sql_area_hit_ratio = sql_area['pinhits'] / sql_area['pins']
sql_area_reloads = sql_area['reloads']

# Soft parse ratio: 1 - hard_parses / total_parses
parse_total = get_stat('parse count (total)')
parse_hard = get_stat('parse count (hard)')
soft_parse_ratio = 1.0 - (parse_hard / parse_total)

# PGA stats
pga_cache_hit = float(
    query_one("SELECT value FROM pgastat WHERE TRIM(name) = 'cache hit percentage'")['value']
)
pga_over_alloc = int(
    query_one("SELECT value FROM pgastat WHERE TRIM(name) = 'over allocation count'")['value']
)

# Current parameter values
current_cache_bytes = int(
    query_one("SELECT value FROM parameter WHERE name = 'db_cache_size'")['value']
)
current_cache_mb = current_cache_bytes // (1024 * 1024)
current_pga_bytes = int(
    query_one("SELECT value FROM parameter WHERE name = 'pga_aggregate_target'")['value']
)
current_pga_mb = current_pga_bytes // (1024 * 1024)
db_block_size = int(
    query_one("SELECT value FROM parameter WHERE name = 'db_block_size'")['value']
)
cursor_sharing = query_one(
    "SELECT value FROM parameter WHERE name = 'cursor_sharing'"
)['value'].strip()


# ══════════════════════════════════════════════════════════════════════════
# STEP 3: Advisory analysis
# ══════════════════════════════════════════════════════════════════════════

# DB cache advice — exclude corrupted rows (negative factor)
cache_advice = query(
    "SELECT size_for_estimate, estd_physical_read_factor, estd_physical_reads "
    "FROM db_cache_advice "
    "WHERE name = 'DEFAULT' AND block_size = ? AND advice_status = 'ON' "
    "AND estd_physical_read_factor >= 0 "
    "ORDER BY size_for_estimate",
    (db_block_size,)
)

# Find inflection point: where marginal improvement drops below threshold
recommended_cache_mb = current_cache_mb
prev_factor = None
for i, row in enumerate(cache_advice):
    size_mb = row['size_for_estimate']
    factor = row['estd_physical_read_factor']
    if size_mb <= current_cache_mb:
        prev_factor = factor
        continue
    if prev_factor is not None:
        improvement = prev_factor - factor
        if improvement < 0.02:
            recommended_cache_mb = cache_advice[i - 1]['size_for_estimate']
            break
        prev_factor = factor
    else:
        prev_factor = factor

if recommended_cache_mb <= current_cache_mb:
    for row in cache_advice:
        if row['estd_physical_read_factor'] <= 0.40 and row['size_for_estimate'] > current_cache_mb:
            recommended_cache_mb = row['size_for_estimate']
            break

# PGA target advice — find minimum size where over-allocation = 0
pga_advice = query(
    "SELECT pga_target_for_estimate, estd_overalloc_count, estd_pga_cache_hit_percentage "
    "FROM pga_target_advice ORDER BY pga_target_for_estimate"
)

recommended_pga_bytes = current_pga_bytes
recommended_pga_mb = current_pga_mb
for row in pga_advice:
    if row['estd_overalloc_count'] == 0:
        recommended_pga_bytes = row['pga_target_for_estimate']
        recommended_pga_mb = recommended_pga_bytes // (1024 * 1024)
        break


# ══════════════════════════════════════════════════════════════════════════
# STEP 4: Wait event analysis
# ══════════════════════════════════════════════════════════════════════════

non_idle_events = query(
    "SELECT event, total_waits, time_waited_micro, avg_wait_micro, wait_class "
    "FROM system_event WHERE TRIM(wait_class) != 'Idle' "
    "ORDER BY time_waited_micro DESC"
)

top_waits = []
for row in non_idle_events[:10]:
    top_waits.append({
        'event': row['event'].strip(),
        'total_waits': row['total_waits'],
        'time_waited_seconds': row['time_waited_micro'] / 1_000_000,
        'avg_wait_ms': row['avg_wait_micro'] / 1000,
        'wait_class': row['wait_class'].strip(),
    })


# ══════════════════════════════════════════════════════════════════════════
# STEP 5: Segment contention analysis
# ══════════════════════════════════════════════════════════════════════════

seg_rows = query(
    "SELECT owner, object_name, statistic_name, SUM(value) as total "
    "FROM segment_statistics GROUP BY owner, object_name, statistic_name"
)

seg_bbw = {}
seg_itl = {}
seg_rlw = {}
for row in seg_rows:
    key = f"{row['owner'].strip()}.{row['object_name'].strip()}"
    stat = row['statistic_name'].strip()
    if stat == 'buffer busy waits':
        seg_bbw[key] = seg_bbw.get(key, 0) + row['total']
    elif stat == 'ITL waits':
        seg_itl[key] = seg_itl.get(key, 0) + row['total']
    elif stat == 'row lock waits':
        seg_rlw[key] = seg_rlw.get(key, 0) + row['total']

hot_segment = max(seg_bbw, key=seg_bbw.get)
hot_bbw = seg_bbw[hot_segment]
hot_itl = seg_itl.get(hot_segment, 0)
hot_rlw = seg_rlw.get(hot_segment, 0)


# ══════════════════════════════════════════════════════════════════════════
# STEP 6: SQL analysis
# ══════════════════════════════════════════════════════════════════════════

sql_rows = query("SELECT * FROM sqlarea")

# Read explain plans
plan_dir = '/app/data/explain_plans'
plans = {}
for fname in os.listdir(plan_dir):
    if fname.endswith('.txt'):
        plans[fname] = read_text(os.path.join(plan_dir, fname))

problematic_sql = []
for row in sql_rows:
    sql_id = row['sql_id'].strip()
    executions = row['executions']
    buffer_gets = row['buffer_gets']
    sql_text = row['sql_text'].strip()
    gets_per_exec = buffer_gets / executions if executions > 0 else buffer_gets
    issues = []

    if '/*+ FULL' in sql_text.upper():
        issues.append('FULL hint forcing unnecessary full table scan')
    if 'NO_INDEX' in sql_text.upper():
        issues.append('NO_INDEX hint preventing index usage')
    if gets_per_exec > 5000 and executions > 100:
        issues.append(f'High buffer gets per execution ({gets_per_exec:.0f})')

    if issues:
        problematic_sql.append({
            'sql_id': sql_id,
            'executions': executions,
            'buffer_gets': buffer_gets,
            'gets_per_exec': round(gets_per_exec, 1),
            'elapsed_seconds': round(row['elapsed_time_us'] / 1_000_000, 2),
            'issues': issues,
            'sql_text_preview': sql_text[:120],
        })


# ══════════════════════════════════════════════════════════════════════════
# STEP 7: Build findings
# ══════════════════════════════════════════════════════════════════════════

findings = []

# Helpers for wait event lookup
def find_wait(event_name):
    for w in top_waits:
        if w['event'] == event_name:
            return w
    return {'time_waited_seconds': 0}


# F1: Buffer cache undersized
findings.append({
    'id': 'F1',
    'severity': 'HIGH',
    'category': 'Memory - Buffer Cache',
    'description': (
        f'Buffer cache hit ratio is {buffer_cache_hit_ratio:.4f} '
        f'({buffer_cache_hit_ratio*100:.1f}%), significantly below the 95% '
        f'OLTP target. Current DB_CACHE_SIZE is {current_cache_mb} MB. '
        f'db file sequential read is the dominant wait event at '
        f'{find_wait("db file sequential read")["time_waited_seconds"]:.0f}s.'
    ),
    'root_cause': (
        f'DB_CACHE_SIZE undersized at {current_cache_mb} MB. Advisory inflection '
        f'point at {recommended_cache_mb} MB. Physical reads cache '
        f'({physical_reads_cache:,}) cause excessive I/O waits.'
    ),
})

# F2: Hard parsing / cursor sharing
findings.append({
    'id': 'F2',
    'severity': 'HIGH',
    'category': 'Parsing - Cursor Sharing',
    'description': (
        f'Soft parse ratio is {soft_parse_ratio:.4f} ({soft_parse_ratio*100:.1f}%), '
        f'far below the 99% OLTP target. Hard parses: {parse_hard:,} of '
        f'{parse_total:,} total ({parse_hard/parse_total*100:.1f}% hard parse ratio). '
        f'Library cache hit ratio: {library_cache_hit_ratio:.4f}. '
        f'SQL AREA pin hit ratio: {sql_area_hit_ratio:.4f}, reloads: {sql_area_reloads:,}. '
        f'CURSOR_SHARING is currently {cursor_sharing}. '
        f'latch: shared pool contention at '
        f'{find_wait("latch: shared pool")["time_waited_seconds"]:.0f}s.'
    ),
    'root_cause': (
        'Application generates literal SQL instead of using bind variables, '
        'causing excessive hard parsing. Confirmed by low soft parse ratio, '
        'high SQL AREA reloads, shared pool latch contention, and '
        'cursor: pin S wait on X events. CURSOR_SHARING=EXACT exacerbates this.'
    ),
})

# F3: PGA undersized
findings.append({
    'id': 'F3',
    'severity': 'HIGH',
    'category': 'Memory - PGA',
    'description': (
        f'PGA over-allocation count: {pga_over_alloc:,} (must be 0). '
        f'PGA cache hit: {pga_cache_hit}%. '
        f'Current PGA_AGGREGATE_TARGET: {current_pga_mb} MB. '
        f'Advisory shows zero over-allocation at {recommended_pga_mb} MB.'
    ),
    'root_cause': (
        f'PGA_AGGREGATE_TARGET at {current_pga_mb} MB is insufficient. '
        f'Over-allocation count of {pga_over_alloc:,} means work areas '
        f'spill to temp tablespace. Must increase to {recommended_pga_mb} MB.'
    ),
})

# F4: Hot segment contention
findings.append({
    'id': 'F4',
    'severity': 'MEDIUM',
    'category': 'Contention - Hot Segment',
    'description': (
        f'ORDERS table is a hot segment with {hot_bbw:,} buffer busy waits, '
        f'{hot_itl:,} ITL waits, and {hot_rlw:,} row lock waits. '
        f'V$WAITSTAT data block class dominates. '
        f'This drives buffer busy waits and latch: cache buffers chains contention.'
    ),
    'root_cause': (
        'Heavy concurrent DML on ORDERS table causes data block contention. '
        'ITL waits indicate INITRANS too low for concurrency level. '
        'Buffer busy waits on table and PK_ORDERS index suggest right-hand '
        'index contention from sequence-generated keys.'
    ),
})

# F5: Problematic SQL
desc_parts = []
for ps in problematic_sql:
    desc_parts.append(f"SQL {ps['sql_id']}: {', '.join(ps['issues'])}")

findings.append({
    'id': 'F5',
    'severity': 'MEDIUM',
    'category': 'SQL - Execution Plans',
    'description': (
        'Problematic SQL with suboptimal execution plans: '
        + '; '.join(desc_parts) + '. '
        'Missing index on ORDERS(STATUS) forces full table scan for '
        'high-frequency query (987K executions).'
    ),
    'root_cause': (
        'Optimizer hints (FULL, NO_INDEX) force suboptimal full table scans. '
        'Missing index on ORDERS(STATUS) causes repeated full table scan '
        'for high-selectivity (0.08%) predicate.'
    ),
})


# ══════════════════════════════════════════════════════════════════════════
# STEP 8: Build remediation SQL
# ══════════════════════════════════════════════════════════════════════════

remediation_lines = [
    '-- Oracle 19c Performance Remediation',
    '-- Derived from V$ performance view analysis and advisory data',
    '',
    '-- Increase buffer cache to advisory inflection point',
    f'ALTER SYSTEM SET db_cache_size = {recommended_cache_mb * 1024 * 1024} SCOPE=BOTH;',
    '',
    '-- Enable cursor sharing to reduce hard parsing',
    "ALTER SYSTEM SET cursor_sharing = 'FORCE' SCOPE=BOTH;",
    '',
    '-- Increase session cached cursors',
    'ALTER SYSTEM SET session_cached_cursors = 100 SCOPE=SPFILE;',
    '',
    '-- Increase PGA target to eliminate over-allocation',
    f'ALTER SYSTEM SET pga_aggregate_target = {recommended_pga_bytes} SCOPE=BOTH;',
    '',
    '-- Increase INITRANS on ORDERS table for concurrency',
    'ALTER TABLE APPUSER.ORDERS INITRANS 16;',
    '',
    '-- Create missing index for high-frequency STATUS lookup',
    'CREATE INDEX APPUSER.IDX_ORDERS_STATUS ON APPUSER.ORDERS(STATUS);',
]


# ══════════════════════════════════════════════════════════════════════════
# STEP 9: Audit the prior analysis
# ══════════════════════════════════════════════════════════════════════════

with open('/app/data/prior_analysis.json') as f:
    prior = json.load(f)

prior_bchr = prior['metrics'].get('buffer_cache_hit_ratio', 0)
prior_cache_rec = prior['metrics'].get('recommended_db_cache_size_mb', 0)
prior_pga_rec = prior['metrics'].get('recommended_pga_target_mb', 0)

prior_assessments = [
    {
        'finding_id': 'P1',
        'verdict': 'partially_incorrect',
        'explanation': (
            f'Buffer cache hit ratio was calculated as {prior_bchr} using total '
            f'physical reads (6,655,654) which includes physical reads direct. '
            f'The correct formula uses physical reads cache (5,421,087) only, '
            f'yielding {buffer_cache_hit_ratio:.4f}. Direct path reads bypass '
            f'the buffer cache and must not be counted. Additionally, the '
            f'recommended cache size of {prior_cache_rec} MB is too conservative '
            f'— the advisory inflection point is at {recommended_cache_mb} MB.'
        ),
    },
    {
        'finding_id': 'P2',
        'verdict': 'incorrect',
        'explanation': (
            'Redo log contention finding is a misdiagnosis. The log file sync '
            'average wait of 3ms is within normal range for OLTP workloads. '
            'Total redo-related foreground wait (6,470s) is ~12.7% of DB time '
            '(50,834s) which is not critical. The actual dominant issues are '
            'buffer cache undersizing, hard parsing/cursor sharing, and PGA '
            'sizing — not redo infrastructure. The recommended changes (more '
            'log groups, larger log buffer, NVMe for redo) are unnecessary '
            'and would divert resources from higher-impact fixes.'
        ),
    },
    {
        'finding_id': 'P3',
        'verdict': 'partially_incorrect',
        'explanation': (
            f'PGA diagnosis is directionally correct but the recommendation '
            f'of {prior_pga_rec} MB is insufficient. At {prior_pga_rec} MB, '
            f'over-allocation count is still 412 (non-zero). The target must '
            f'be {recommended_pga_mb} MB where over-allocation reaches zero. '
            f'The prior analysis stopped at the first major improvement rather '
            f'than finding the zero-overallocation threshold.'
        ),
    },
]

missed_issues = [
    {
        'category': 'Parsing - Cursor Sharing',
        'description': (
            f'Soft parse ratio is only {soft_parse_ratio*100:.1f}%, far below '
            f'the 99% OLTP target. CURSOR_SHARING=EXACT with literal SQL '
            f'causes {parse_hard:,} hard parses out of {parse_total:,} total. '
            f'This drives shared pool latch contention '
            f'({find_wait("latch: shared pool")["time_waited_seconds"]:.0f}s) '
            f'and cursor: pin S wait on X events. This is the highest-impact '
            f'missed issue.'
        ),
    },
    {
        'category': 'Contention - Hot Segment',
        'description': (
            f'ORDERS table has {hot_bbw:,} buffer busy waits and '
            f'{hot_itl:,} ITL waits, making it the primary contention point. '
            f'This was completely overlooked despite ORDERS being the dominant '
            f'hot segment in the database.'
        ),
    },
    {
        'category': 'SQL - Execution Plans',
        'description': (
            'Multiple SQL statements have forced bad execution plans via '
            'FULL and NO_INDEX hints, and a high-frequency query on '
            'ORDERS.STATUS lacks a supporting index (987K executions with '
            'full table scan). These SQL-level issues were not analyzed.'
        ),
    },
]

audit_report = {
    'prior_findings_assessment': prior_assessments,
    'missed_issues': missed_issues,
    'data_anomalies': data_anomalies,
}


# ══════════════════════════════════════════════════════════════════════════
# STEP 10: Write output files
# ══════════════════════════════════════════════════════════════════════════

os.makedirs('/app/output', exist_ok=True)

metrics = {
    'buffer_cache_hit_ratio': round(buffer_cache_hit_ratio, 6),
    'library_cache_hit_ratio': round(library_cache_hit_ratio, 6),
    'soft_parse_ratio': round(soft_parse_ratio, 6),
    'recommended_db_cache_size_mb': recommended_cache_mb,
    'recommended_pga_target_mb': recommended_pga_mb,
}

with open('/app/output/metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)

with open('/app/output/findings.json', 'w') as f:
    json.dump(findings, f, indent=2)

with open('/app/output/remediation.sql', 'w') as f:
    f.write('\n'.join(remediation_lines) + '\n')

with open('/app/output/audit_report.json', 'w') as f:
    json.dump(audit_report, f, indent=2)

conn.close()

print("Audit complete. Output files written to /app/output/")
print(f"  metrics.json:      {len(metrics)} metrics")
print(f"  findings.json:     {len(findings)} issues")
print(f"  remediation.sql:   {len(remediation_lines)} lines")
print(f"  audit_report.json: {len(prior_assessments)} assessments, "
      f"{len(missed_issues)} missed, {len(data_anomalies)} anomalies")
