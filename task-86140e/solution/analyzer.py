#!/usr/bin/env python3
"""
Analyze TiDB EXPLAIN ANALYZE execution plans to diagnose performance issues
and compute operator-level metrics.

"""

import json
import re
import yaml


def parse_time_to_seconds(time_str):
    """Parse a TiDB time string to seconds."""
    time_str = time_str.strip()

    # Compound: 2m30.1s
    m = re.match(r'^(\d+)m([\d.]+)s$', time_str)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))

    if time_str.endswith('ms'):
        return float(time_str[:-2]) / 1000.0
    elif time_str.endswith('us'):
        return float(time_str[:-2]) / 1_000_000.0
    elif time_str.endswith('ns'):
        return float(time_str[:-2]) / 1_000_000_000.0
    elif time_str.endswith('s'):
        return float(time_str[:-1])
    else:
        return float(time_str)


def get_exec_info_for_operator(plan_text, operator_substr):
    """Find the execution info column for the first row matching operator_substr."""
    for line in plan_text.split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        if operator_substr not in line:
            continue
        parts = line.split('|')
        if len(parts) >= 8:
            return parts[6].strip()
    return None


def analyze_case1(plan_text):
    """Analyze lock contention in a point query."""
    exec_info = get_exec_info_for_operator(plan_text, 'Point_Get')
    if not exec_info:
        raise ValueError("Could not find Point_Get operator in plan")

    # Total query time (match 'time:' but not 'total_time:', 'rpc_time:', etc.)
    total_m = re.search(r'(?<![_a-zA-Z])time:([\d.]+(?:ms|us|ns|s))', exec_info)
    total_time = parse_time_to_seconds(total_m.group(1))

    # ResolveLock total_time
    rl_m = re.search(r'ResolveLock:\{[^}]*total_time:([\d.]+(?:ms|us|ns|s))', exec_info)
    rl_time = parse_time_to_seconds(rl_m.group(1))

    # Get total_time (actual data access)
    get_m = re.search(r'Get:\{[^}]*total_time:([\d.]+(?:ms|us|ns|s))', exec_info)
    get_time = parse_time_to_seconds(get_m.group(1))

    # txnNotFound_backoff retries
    bo_m = re.search(r'txnNotFound_backoff:\{num:(\d+)', exec_info)
    backoff_retries = int(bo_m.group(1))

    return {
        "bottleneck_operator": "Point_Get_1",
        "root_cause": "lock_contention",
        "resolve_lock_time_sec": rl_time,
        "lock_time_fraction": round(rl_time / total_time, 4),
        "data_access_time_ms": round(get_time * 1000, 1),
        "backoff_retries": backoff_retries
    }


def analyze_case2(plan_text, config):
    """Analyze operator concurrency in an IndexLookUp query."""
    exec_info = get_exec_info_for_operator(plan_text, 'IndexLookUp')
    if not exec_info:
        raise ValueError("Could not find IndexLookUp operator in plan")

    # table_task concurrency (explicitly shown)
    tc_m = re.search(r'table_task:\s*\{[^}]*concurrency:\s*(\d+)', exec_info)
    table_task_concurrency = int(tc_m.group(1)) if tc_m else 1

    # index_task concurrency (may not be shown → default 1)
    ic_m = re.search(r'index_task:\s*\{[^}]*concurrency:\s*(\d+)', exec_info)
    index_task_concurrency = int(ic_m.group(1)) if ic_m else 1

    # distsql scan concurrency from system config
    distsql_scan_concurrency = config['tidb_distsql_scan_concurrency']

    # Max parallel cop tasks per path = operator concurrency × distsql_scan_concurrency
    index_path = index_task_concurrency * distsql_scan_concurrency
    table_path = table_task_concurrency * distsql_scan_concurrency

    return {
        "index_task_concurrency": index_task_concurrency,
        "table_task_concurrency": table_task_concurrency,
        "distsql_scan_concurrency": distsql_scan_concurrency,
        "index_path_max_parallel_cop_tasks": index_path,
        "table_path_max_parallel_cop_tasks": table_path,
        "total_max_parallel_cop_tasks": index_path + table_path
    }


def analyze_case3(fast_text, slow_text):
    """Analyze MVCC tombstone scanning from MAX vs MIN asymmetry."""
    # --- Fast query (MAX, descending scan) ---
    fast_ir_info = get_exec_info_for_operator(fast_text, 'IndexReader')
    fast_cop_m = re.search(r'cop_task:\s*\{num:\s*(\d+)', fast_ir_info)
    fast_cop_tasks = int(fast_cop_m.group(1))

    # Single cop task → uses 'proc_keys' (not 'max_proc_keys')
    fast_pk_m = re.search(r'(?<![_a-zA-Z])proc_keys:\s*(\d+)', fast_ir_info)
    fast_proc_keys = int(fast_pk_m.group(1))

    # --- Slow query (MIN, ascending scan) ---
    slow_ir_info = get_exec_info_for_operator(slow_text, 'IndexReader')
    slow_cop_m = re.search(r'cop_task:\s*\{num:\s*(\d+)', slow_ir_info)
    slow_cop_tasks = int(slow_cop_m.group(1))

    # Multiple cop tasks → uses 'max_proc_keys'
    slow_mpk_m = re.search(r'max_proc_keys:\s*(\d+)', slow_ir_info)
    slow_max_proc_keys = int(slow_mpk_m.group(1))

    # Root operator times
    fast_root_info = get_exec_info_for_operator(fast_text, 'Limit_14')
    fast_time_m = re.search(r'(?<![_a-zA-Z])time:([\d.]+(?:ms|us|ns|s))', fast_root_info)
    fast_time = parse_time_to_seconds(fast_time_m.group(1))

    slow_root_info = get_exec_info_for_operator(slow_text, 'Limit_14')
    slow_time_m = re.search(r'(?<![_a-zA-Z])time:([\d.]+(?:ms|us|ns|s))', slow_root_info)
    slow_time = parse_time_to_seconds(slow_time_m.group(1))

    return {
        "bottleneck_operator": "IndexReader_45",
        "root_cause": "mvcc_tombstone_scan",
        "fast_query_cop_tasks": fast_cop_tasks,
        "slow_query_cop_tasks": slow_cop_tasks,
        "fast_query_proc_keys": fast_proc_keys,
        "slow_query_max_proc_keys": slow_max_proc_keys,
        "key_amplification_factor": round(slow_max_proc_keys / fast_proc_keys, 2),
        "cop_task_ratio": slow_cop_tasks // fast_cop_tasks,
        "slow_query_time_sec": slow_time,
        "fast_query_time_sec": fast_time
    }


def main():
    # Read system configuration
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)

    # Read execution plan files
    with open('/app/plans/query_001.plan') as f:
        case1_plan = f.read()
    with open('/app/plans/query_002.plan') as f:
        case2_plan = f.read()
    with open('/app/plans/query_003a.plan') as f:
        case3a_plan = f.read()
    with open('/app/plans/query_003b.plan') as f:
        case3b_plan = f.read()

    # Analyze each diagnostic case
    results = {
        "case1_lock_contention": analyze_case1(case1_plan),
        "case2_concurrency": analyze_case2(case2_plan, config),
        "case3_mvcc_tombstone": analyze_case3(case3a_plan, case3b_plan)
    }

    # Write structured output
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
