#!/usr/bin/env python3
"""TiDB EXPLAIN ANALYZE diagnostic analyzer.

Uses plan-ctl to decode .planpb binary plan files, sqlite3 data via
environment variables, and jq-extracted cluster state to produce
JSON diagnostic reports for each incident.
"""


import json
import os
import re
import sqlite3
import subprocess


# ─── plan-ctl helpers ────────────────────────────────────────────────

def planctl_operators(planpb_path):
    """Get operator tree as list of dicts via plan-ctl operators --format json."""
    result = subprocess.run(
        ['plan-ctl', 'operators', planpb_path, '--format', 'json'],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def planctl_exec_info(planpb_path, operator_id, key=None):
    """Get parsed execution info for an operator via plan-ctl exec-info."""
    cmd = ['plan-ctl', 'exec-info', planpb_path, operator_id]
    if key:
        cmd.extend(['--key', key])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


# ─── Time parsing ────────────────────────────────────────────────────

def parse_time(s):
    """Convert a TiDB time string to milliseconds."""
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0
    s = s.replace('\u00b5', 'u').replace('\u03bc', 'u')
    if s.endswith('ns'):
        return float(s[:-2]) / 1e6
    if s.endswith('us'):
        return float(s[:-2]) / 1e3
    if s.endswith('ms'):
        return float(s[:-2])
    if s.endswith('s'):
        m = re.match(r'^(?:(\d+)m)?(\d+(?:\.\d+)?)s$', s)
        if m:
            minutes = int(m.group(1)) if m.group(1) else 0
            seconds = float(m.group(2))
            return (minutes * 60 + seconds) * 1000
    try:
        return float(s)
    except ValueError:
        return 0.0


def _cop_task(ei):
    return ei.get('cop_task', {})


def _distsql_concurrency(cop_task, config):
    if isinstance(cop_task, dict) and 'distsql_concurrency' in cop_task:
        return int(cop_task['distsql_concurrency'])
    return config['tidb_distsql_scan_concurrency']


# ─── Case analyzers ─────────────────────────────────────────────────

def analyze_case1(plans_dir, config):
    f = os.path.join(plans_dir, 'case1_lock_contention.planpb')
    ops = planctl_operators(f)
    op = ops[0]
    ei = planctl_exec_info(f, op['id'])

    total_ms = parse_time(ei.get('time'))
    rl = ei.get('ResolveLock', {})
    rl_ms = parse_time(rl.get('total_time')) if isinstance(rl, dict) else 0.0
    gt = ei.get('Get', {})
    gt_ms = parse_time(gt.get('total_time')) if isinstance(gt, dict) else 0.0
    bo = ei.get('txnNotFound_backoff', {})
    bo_num = int(bo.get('num', '0')) if isinstance(bo, dict) else 0

    return {
        'bottleneck_operator': op['id'],
        'root_cause': 'lock_contention',
        'self_time_ms': total_ms,
        'resolve_lock_time_ms': rl_ms,
        'get_time_ms': gt_ms,
        'backoff_retries': bo_num,
    }


def analyze_case2(plans_dir, config):
    f = os.path.join(plans_dir, 'case2_concurrency.planpb')
    ops = planctl_operators(f)

    lookup = ops[0]
    idx_scan = ops[1]
    tbl_scan = ops[2]

    ei = planctl_exec_info(f, lookup['id'])
    idx_ei = planctl_exec_info(f, idx_scan['id'])
    tbl_ei = planctl_exec_info(f, tbl_scan['id'])

    idx_task = ei.get('index_task', {})
    idx_conc = int(idx_task.get('concurrency', '1')) if isinstance(idx_task, dict) else 1

    tbl_task = ei.get('table_task', {})
    tbl_conc = int(tbl_task.get('concurrency', '1')) if isinstance(tbl_task, dict) else 1

    idx_cop = _cop_task(idx_ei)
    tbl_cop = _cop_task(tbl_ei)

    idx_distsql = _distsql_concurrency(idx_cop, config)
    tbl_distsql = _distsql_concurrency(tbl_cop, config)

    max_conc = tbl_conc * tbl_distsql

    idx_avg = parse_time(idx_cop.get('avg'))
    idx_num = int(idx_cop.get('num', '0'))
    idx_est = idx_avg * idx_num / idx_distsql if idx_distsql else 0.0

    tbl_avg = parse_time(tbl_cop.get('avg'))
    tbl_num = int(tbl_cop.get('num', '0'))
    tbl_est = tbl_avg * tbl_num / tbl_distsql if tbl_distsql else 0.0

    return {
        'bottleneck_operator': lookup['id'],
        'index_task_concurrency': idx_conc,
        'table_task_concurrency': tbl_conc,
        'index_distsql_concurrency': idx_distsql,
        'table_distsql_concurrency': tbl_distsql,
        'max_concurrent_cop_tasks': max_conc,
        'index_cop_estimated_time_ms': idx_est,
        'table_cop_estimated_time_ms': tbl_est,
    }


def analyze_case3(plans_dir, config):
    fmax = os.path.join(plans_dir, 'case3_max.planpb')
    fmin = os.path.join(plans_dir, 'case3_min.planpb')

    max_ops = planctl_operators(fmax)
    min_ops = planctl_operators(fmin)

    max_ir = max_scan = min_ir = min_scan = None
    for op in max_ops:
        if 'IndexReader' in op['id']:
            max_ir = op
        if 'IndexFullScan' in op['id']:
            max_scan = op
    for op in min_ops:
        if 'IndexReader' in op['id']:
            min_ir = op
        if 'IndexFullScan' in op['id']:
            min_scan = op

    max_ir_ei = planctl_exec_info(fmax, max_ir['id'])
    min_ir_ei = planctl_exec_info(fmin, min_ir['id'])

    max_cop = _cop_task(max_ir_ei)
    min_cop = _cop_task(min_ir_ei)

    max_tasks = int(max_cop.get('num', '0'))
    min_tasks = int(min_cop.get('num', '0'))

    max_pk = int(max_cop.get('proc_keys', max_cop.get('max_proc_keys', '0')))
    min_mpk = int(min_cop.get('max_proc_keys', min_cop.get('proc_keys', '0')))

    min_avg = parse_time(min_cop.get('avg'))
    distsql = _distsql_concurrency(min_cop, config)
    min_est = min_avg * min_tasks / distsql if distsql else 0.0

    max_order = 'desc' if 'desc' in (max_scan['operator_info'] or '') else 'asc'
    min_order = 'desc' if 'desc' in (min_scan['operator_info'] or '') else 'asc'

    return {
        'bottleneck_operator': min_ir['id'],
        'root_cause': 'mvcc_tombstone',
        'max_query': {
            'cop_tasks': max_tasks,
            'proc_keys': max_pk,
            'scan_order': max_order,
        },
        'min_query': {
            'cop_tasks': min_tasks,
            'max_proc_keys': min_mpk,
            'estimated_cop_time_ms': min_est,
            'scan_order': min_order,
        },
        'cop_task_ratio': min_tasks / max_tasks if max_tasks else 0.0,
        'proc_keys_ratio': min_mpk / max_pk if max_pk else 0.0,
        'gc_tombstone_keys_cleaned': config['gc_tombstone_keys_cleaned'],
        'max_store_sst_count': config['max_store_sst_count'],
    }


def analyze_case4(plans_dir, config):
    f = os.path.join(plans_dir, 'case4_complex_join.planpb')
    ops = planctl_operators(f)

    root = ops[0]
    root_ei = planctl_exec_info(f, root['id'])
    children = [op for op in ops if op['depth'] == 1]

    root_time = parse_time(root_ei.get('time'))
    children_times = {}
    for c in children:
        c_ei = planctl_exec_info(f, c['id'])
        children_times[c['id']] = parse_time(c_ei.get('time'))
    hj_self = root_time - sum(children_times.values())

    bottleneck = max(children, key=lambda c: children_times[c['id']])

    table_reader = next(o for o in ops if 'TableReader' in o['id'])
    tr_ei = planctl_exec_info(f, table_reader['id'])
    tr_cop = _cop_task(tr_ei)
    tr_avg = parse_time(tr_cop.get('avg'))
    tr_num = int(tr_cop.get('num', '0'))
    tr_distsql = _distsql_concurrency(tr_cop, config)
    tr_est = tr_avg * tr_num / tr_distsql if tr_distsql else 0.0

    index_lookup = next(o for o in ops if 'IndexLookUp' in o['id'])
    il_ei = planctl_exec_info(f, index_lookup['id'])
    il_tbl_task = il_ei.get('table_task', {})
    il_tbl_conc = int(il_tbl_task.get('concurrency', '1')) if isinstance(il_tbl_task, dict) else 1

    trs = next(o for o in ops if 'TableRowIDScan' in o['id'])
    trs_ei = planctl_exec_info(f, trs['id'])
    trs_cop = _cop_task(trs_ei)
    trs_distsql = _distsql_concurrency(trs_cop, config)
    il_max_conc = il_tbl_conc * trs_distsql

    trs_avg = parse_time(trs_cop.get('avg'))
    trs_num = int(trs_cop.get('num', '0'))
    probe_est = trs_avg * trs_num / trs_distsql if trs_distsql else 0.0

    op_list = []
    for o in ops:
        time_ms = None
        if o['task'] == 'root':
            o_ei = planctl_exec_info(f, o['id'])
            time_ms = parse_time(o_ei.get('time'))
        op_list.append({
            'id': o['id'],
            'task_type': o['task'],
            'time_ms': time_ms,
        })

    return {
        'bottleneck_operator': bottleneck['id'],
        'operators': op_list,
        'hashjoin_self_time_ms': hj_self,
        'table_reader_cop_estimated_time_ms': tr_est,
        'probe_cop_estimated_time_ms': probe_est,
        'indexlookup_max_concurrent_cop': il_max_conc,
    }


# ─── Triage summary (cross-incident evaluation) ─────────────────────

INCIDENT_CASE_MAP = {
    'case1': 'INC-001',
    'case2': 'INC-002',
    'case3': 'INC-003',
    'case4': 'INC-004',
}


def analyze_triage_summary(case_reports):
    """Cross-incident risk evaluation synthesizing all findings."""

    # Priority ranking from slow_queries (max exec_time_ms per incident)
    conn = sqlite3.connect('/app/diagnostics.db')
    c = conn.cursor()
    c.execute("""
        SELECT incident_id, MAX(exec_time_ms) as max_exec_time
        FROM slow_queries
        WHERE incident_id IS NOT NULL
        GROUP BY incident_id
        ORDER BY max_exec_time DESC
    """)
    rows = c.fetchall()
    conn.close()

    priority_ranking = [r[0] for r in rows]
    exec_times = {r[0]: r[1] for r in rows}

    # Classify root cause groups based on diagnostic findings
    gc_related = []
    concurrency_related = []

    for case_name, report in case_reports.items():
        inc_id = INCIDENT_CASE_MAP[case_name]
        rc = report.get('root_cause', '')
        if rc in ('lock_contention', 'mvcc_tombstone'):
            gc_related.append(inc_id)
        elif 'max_concurrent_cop_tasks' in report or 'indexlookup_max_concurrent_cop' in report:
            concurrency_related.append(inc_id)

    gc_related.sort()
    concurrency_related.sort()

    # Cluster risk metrics from topology
    with open('/app/cluster_topology.json') as f:
        topo = json.load(f)

    stores = topo['stores']
    stores_above_90 = sum(1 for s in stores if s['capacity']['used_ratio'] > 0.90)
    min_avail = min(s['capacity']['available_gb'] for s in stores)
    gc_last = topo['gc']['last_run']
    gc_tomb_ratio = gc_last['tombstone_keys_cleaned'] / gc_last['keys_processed']
    max_sst = max(s['metrics']['sst_file_count'] for s in stores)
    total_compaction = sum(s['metrics']['compaction_pending_bytes_mb'] for s in stores)

    # Impact assessment
    gc_latency = sum(exec_times.get(inc, 0) for inc in gc_related)
    conc_latency = sum(exec_times.get(inc, 0) for inc in concurrency_related)
    highest_impact = 'gc_related' if gc_latency >= conc_latency else 'concurrency_related'

    if gc_tomb_ratio > 0.40:
        gc_urgency = 'high'
    elif gc_tomb_ratio > 0.25:
        gc_urgency = 'medium'
    else:
        gc_urgency = 'low'

    max_used_ratio = max(s['capacity']['used_ratio'] for s in stores)
    if max_used_ratio > 0.90:
        storage_urgency = 'critical'
    elif max_used_ratio > 0.80:
        storage_urgency = 'warning'
    else:
        storage_urgency = 'normal'

    return {
        'priority_ranking': priority_ranking,
        'root_cause_groups': {
            'gc_related': gc_related,
            'concurrency_related': concurrency_related,
        },
        'cluster_risk_metrics': {
            'stores_above_90pct_usage': stores_above_90,
            'min_available_storage_gb': min_avail,
            'gc_tombstone_ratio': gc_tomb_ratio,
            'max_sst_file_count': max_sst,
            'total_pending_compaction_mb': total_compaction,
        },
        'impact_assessment': {
            'gc_related_total_latency_ms': gc_latency,
            'concurrency_related_total_latency_ms': conc_latency,
            'highest_impact_category': highest_impact,
            'gc_urgency': gc_urgency,
            'storage_urgency': storage_urgency,
        },
    }


# ─── Main ────────────────────────────────────────────────────────────

def main():
    plans_dir = '/app/plans'
    reports_dir = '/app/reports'
    os.makedirs(reports_dir, exist_ok=True)

    config = {
        'tidb_executor_concurrency': int(os.environ.get('TIDB_EXEC_CONCURRENCY', 5)),
        'tidb_distsql_scan_concurrency': int(os.environ.get('TIDB_DISTSQL_SCAN_CONCURRENCY', 15)),
        'gc_tombstone_keys_cleaned': int(os.environ.get('GC_TOMBSTONE_CLEANED', 0)),
        'max_store_sst_count': int(os.environ.get('MAX_STORE_SST_COUNT', 0)),
    }

    case_reports = {}
    cases = [
        ('case1', lambda: analyze_case1(plans_dir, config)),
        ('case2', lambda: analyze_case2(plans_dir, config)),
        ('case3', lambda: analyze_case3(plans_dir, config)),
        ('case4', lambda: analyze_case4(plans_dir, config)),
    ]

    for name, fn in cases:
        report = fn()
        case_reports[name] = report
        out = os.path.join(reports_dir, f'{name}.json')
        with open(out, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'  wrote {out}')

    # Triage summary: cross-incident evaluation
    triage = analyze_triage_summary(case_reports)
    triage_out = os.path.join(reports_dir, 'triage_summary.json')
    with open(triage_out, 'w') as f:
        json.dump(triage, f, indent=2)
    print(f'  wrote {triage_out}')

    print('All diagnostic reports generated.')


if __name__ == '__main__':
    main()
