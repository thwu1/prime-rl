#!/usr/bin/env python3

"""Build and run the consistency monitor at /app/monitor/."""

import os
import subprocess

os.makedirs('/app/monitor', exist_ok=True)

# --- Write consistency monitor script ---
MONITOR_PY = r'''#!/usr/bin/env python3
"""Consistency monitor: compares streaming pipeline against DuckDB oracle."""

import json
import sys
import subprocess
import os

sys.path.insert(0, '/app')


def run_oracle(delay):
    """Invoke the DuckDB oracle for a given watermark delay."""
    subprocess.run(
        ['bash', '/app/oracle/compute.sh', str(delay)],
        check=True, capture_output=True, cwd='/app'
    )
    with open('/app/oracle/batch_results.json') as f:
        return json.load(f)


def run_pipeline(delay):
    """Run the streaming pipeline with a given watermark delay."""
    from engine import IncrementalViewEngine

    txns = []
    with open('/app/data/transactions.jsonl') as f:
        for line in f:
            txns.append(json.loads(line))

    engine = IncrementalViewEngine(watermark_delay=delay)
    for txn in txns:
        engine.ingest(txn['arrival_time'], txn)
    engine.finalize()
    return engine


def jq_compare(pipeline_data, oracle_data, delay):
    """Use jq for structured JSON comparison of pipeline vs oracle output."""
    p_file = f'/tmp/monitor_p_{delay}.json'
    o_file = f'/tmp/monitor_o_{delay}.json'

    with open(p_file, 'w') as f:
        json.dump(pipeline_data, f)
    with open(o_file, 'w') as f:
        json.dump(oracle_data, f)

    try:
        result = subprocess.run(
            ['jq', '-n',
             '--slurpfile', 'p', p_file,
             '--slurpfile', 'o', o_file,
             '{'
             'credits_match: ($p[0].credits == $o[0].credits), '
             'debits_match: ($p[0].debits == $o[0].debits), '
             'total_match: ($p[0].total == $o[0].total)'
             '}'],
            capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {'credits_match': False, 'debits_match': False, 'total_match': False}


def classify_anomalies(engine, oracle, delay):
    """Compare streaming output against oracle and classify failure modes."""
    failure_modes = []
    anomalies = 0

    checkpoints = engine.get_checkpoints()
    if not checkpoints:
        return ['finalization_error'], 1

    final = checkpoints[-1]
    oracle_credits = {int(k): v for k, v in oracle['credits'].items()}
    oracle_debits = {int(k): v for k, v in oracle['debits'].items()}
    all_oracle_accounts = set(oracle_credits.keys()) | set(oracle_debits.keys())

    # Stream desync: total != 0 at any checkpoint
    for cp in checkpoints:
        if cp['total'] != 0:
            if 'stream_desync' not in failure_modes:
                failure_modes.append('stream_desync')
            anomalies += 1

    # Watermark boundary: rejected count mismatch
    if engine.get_rejected_count() != oracle['rejected_count']:
        failure_modes.append('watermark_boundary')
        anomalies += 1

    # Missing accounts: balance doesn't cover all accounts
    if final.get('balance'):
        balance_accounts = set(final['balance'].keys())
        if balance_accounts != all_oracle_accounts:
            failure_modes.append('missing_accounts')
            anomalies += 1

    # Finalization error: final values differ from oracle
    if final.get('credits') != oracle_credits or final.get('debits') != oracle_debits:
        if 'finalization_error' not in failure_modes:
            failure_modes.append('finalization_error')
        anomalies += 1

    # Cross-check with jq for structured comparison
    final_norm = {
        'credits': {str(k): v for k, v in final.get('credits', {}).items()},
        'debits': {str(k): v for k, v in final.get('debits', {}).items()},
        'total': final.get('total', None),
    }
    oracle_norm = {
        'credits': {str(k): v for k, v in oracle.get('credits', {}).items()},
        'debits': {str(k): v for k, v in oracle.get('debits', {}).items()},
        'total': oracle.get('total', None),
    }
    jq_result = jq_compare(final_norm, oracle_norm, delay)

    if not all(jq_result.values()):
        if not failure_modes:
            failure_modes.append('finalization_error')
            anomalies += 1

    return failure_modes, anomalies


def main():
    delays = [0, 1, 5, 10, 20]
    systems = []
    all_consistent = True

    for delay in delays:
        print(f"Auditing watermark_delay={delay}...")
        oracle = run_oracle(delay)
        engine = run_pipeline(delay)
        failure_modes, anomalies = classify_anomalies(engine, oracle, delay)

        consistent = anomalies == 0
        if not consistent:
            all_consistent = False

        systems.append({
            'watermark_delay': delay,
            'consistent': consistent,
            'total_anomalies': anomalies,
            'failure_modes': failure_modes,
        })

    report = {
        'systems': systems,
        'overall_consistent': all_consistent,
    }

    with open('/app/monitor/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to /app/monitor/report.json")
    print(f"Overall consistent: {all_consistent}")


if __name__ == '__main__':
    main()
'''

with open('/app/monitor/consistency_monitor.py', 'w') as f:
    f.write(MONITOR_PY)

# --- Write shell runner ---
RUN_SH = '#!/usr/bin/env bash\n'
RUN_SH += '# Consistency monitor using DuckDB oracle and jq comparison\n'
RUN_SH += 'cd /app\n'
RUN_SH += 'python3 /app/monitor/consistency_monitor.py\n'

with open('/app/monitor/run_monitor.sh', 'w') as f:
    f.write(RUN_SH)
os.chmod('/app/monitor/run_monitor.sh', 0o755)

# Run the monitor
result = subprocess.run(
    ['bash', '/app/monitor/run_monitor.sh'],
    capture_output=True, text=True, cwd='/app'
)
print(result.stdout)
if result.returncode != 0:
    print(f"Monitor error: {result.stderr}")
    raise SystemExit(1)

print("Monitor built and executed successfully.")
