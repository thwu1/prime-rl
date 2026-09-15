#!/usr/bin/env python3
"""
Kernel crash triage system: parses crash reports, deduplicates by stack trace
similarity, evaluates multi-trial patch verification receipts, computes
localization metrics, and writes results to SQLite + JSON.
"""

import re
import json
import os
import sqlite3


# ─── Crash report parsing ──────────────────────────────────────────────

def parse_crash_report(filepath):
    with open(filepath, 'r') as f:
        text = f.read()

    result = {
        'bug_type': None,
        'access_type': None,
        'access_size': None,
        'faulting_function': None,
        'call_trace': [],
        'task_comm': None,
        'task_pid': None,
        'kernel_version': None,
    }

    # Detect format and extract type-specific fields
    if 'BUG: KASAN:' in text:
        m = re.search(r'BUG: KASAN:\s+(\S+)\s+in\s+(\w+)\+', text)
        if m:
            result['bug_type'] = m.group(1)
            result['faulting_function'] = m.group(2)
        m = re.search(r'(Read|Write) of size (\d+) at addr', text)
        if m:
            result['access_type'] = m.group(1).lower()
            result['access_size'] = int(m.group(2))

    elif 'general protection fault' in text.lower():
        result['bug_type'] = 'general-protection-fault'
        m = re.search(r'RIP:\s+\w+:(\w+)\+', text)
        if m:
            result['faulting_function'] = m.group(1)

    elif 'WARNING:' in text:
        result['bug_type'] = 'warning'
        m = re.search(r'WARNING:.*\bat\s+\S+:\d+\s+(\w+)\+', text)
        if m:
            result['faulting_function'] = m.group(1)

    # Task info
    m = re.search(r'by task (\S+)/(\d+)', text)
    if m:
        result['task_comm'] = m.group(1)
        result['task_pid'] = int(m.group(2))
    else:
        m = re.search(r'PID:\s*(\d+)\s+Comm:\s*(\S+)', text)
        if m:
            result['task_pid'] = int(m.group(1))
            result['task_comm'] = m.group(2)

    # Kernel version
    m = re.search(r'(\d+\.\d+\.\d+\S*)\s+#\d+', text)
    if m:
        result['kernel_version'] = m.group(1)

    # Call trace from <TASK>...</TASK> block
    task_match = re.search(r'<TASK>(.*?)</TASK>', text, re.DOTALL)
    if task_match:
        task_block = task_match.group(1)
        frames = re.findall(
            r'(\w+)\+(0x[0-9a-fA-F]+)/(0x[0-9a-fA-F]+)',
            task_block
        )
        result['call_trace'] = [
            {'function': func, 'offset': offset, 'size': size}
            for func, offset, size in frames
        ]

    return result


# ─── Deduplication ─────────────────────────────────────────────────────

def _weighted_jaccard(trace_a, trace_b, top_n=5):
    a = trace_a[:top_n]
    b = trace_b[:top_n]

    pos_a = {}
    for i, frame in enumerate(a):
        fn = frame['function']
        if fn not in pos_a:
            pos_a[fn] = i

    pos_b = {}
    for i, frame in enumerate(b):
        fn = frame['function']
        if fn not in pos_b:
            pos_b[fn] = i

    all_funcs = set(pos_a) | set(pos_b)
    if not all_funcs:
        return 0.0

    num = 0.0
    den = 0.0
    for f in all_funcs:
        wa = 1.0 / (pos_a[f] + 1) if f in pos_a else 0.0
        wb = 1.0 / (pos_b[f] + 1) if f in pos_b else 0.0
        num += min(wa, wb)
        den += max(wa, wb)

    return num / den if den > 0 else 0.0


def deduplicate(reports, threshold=0.7):
    ids = sorted(reports.keys())
    n = len(ids)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            sim = _weighted_jaccard(
                reports[ids[i]]['call_trace'],
                reports[ids[j]]['call_trace']
            )
            if sim >= threshold:
                union(i, j)

    from collections import defaultdict
    groups_map = defaultdict(list)
    for i in range(n):
        groups_map[find(i)].append(ids[i])

    result = [sorted(g) for g in groups_map.values()]
    return sorted(result, key=lambda g: g[0])


# ─── Multi-trial evaluation protocol ──────────────────────────────────

RERUN_SUCCESS = 3
MAX_TRYS = 5


def process_receipts(receipt_paths):
    tracked = {}   # cleaned_id -> {variant -> trial_dict}
    redo = []
    first_run = True

    for path in receipt_paths:
        with open(path, 'r') as f:
            receipt = json.load(f)

        next_redo = []
        for job in receipt['jobs']:
            bug_id = job['bug_id']
            parts = bug_id.split('__')
            cleaned_id = parts[0]
            variant = parts[1] if len(parts) > 1 else '0'

            if not first_run and bug_id not in redo:
                continue

            message = job['execution']['message']
            crash_description = None
            if message is None:
                crash_description = job['execution']['crash_description']

            try:
                if first_run:
                    if crash_description is not None:
                        continue
                    if message.lower() != 'no crash reproduced':
                        continue
                    if cleaned_id not in tracked:
                        tracked[cleaned_id] = {}
                    trial_dict = {i + 1: None for i in range(MAX_TRYS)}
                    trial_dict[1] = message.lower()
                    tracked[cleaned_id][variant] = trial_dict
                    next_redo.append(bug_id)
                else:
                    if (cleaned_id in tracked and
                            variant in tracked[cleaned_id]):
                        trial_dict = tracked[cleaned_id][variant]
                        slot = None
                        for k in sorted(trial_dict.keys()):
                            if trial_dict[k] is None:
                                slot = k
                                break
                        if slot is not None:
                            if message:
                                trial_dict[slot] = message.lower()
                            else:
                                trial_dict[slot] = crash_description

                            clean_count = sum(
                                1 for v in trial_dict.values()
                                if v == 'no crash reproduced'
                            )
                            all_filled = all(
                                v is not None for v in trial_dict.values()
                            )

                            if (clean_count < RERUN_SUCCESS and
                                    not all_filled and
                                    crash_description is None):
                                next_redo.append(bug_id)
            except Exception:
                continue

        redo = next_redo
        first_run = False

    # Final classification
    resolved = []
    unresolved = []

    for cleaned_id, variants in tracked.items():
        for variant, trial_dict in variants.items():
            bug_id = f'{cleaned_id}__{variant}'
            clean_count = sum(
                1 for v in trial_dict.values()
                if v == 'no crash reproduced'
            )
            total_trials = sum(
                1 for v in trial_dict.values() if v is not None
            )
            if clean_count >= RERUN_SUCCESS:
                resolved.append((bug_id, clean_count, total_trials))
            else:
                unresolved.append((bug_id, clean_count, total_trials))

    return {
        'resolved': sorted(resolved, key=lambda x: x[0]),
        'unresolved': sorted(unresolved, key=lambda x: x[0]),
    }


# ─── Localization metrics ─────────────────────────────────────────────

def compute_localization(patch_path, ranked_files):
    with open(patch_path, 'r') as f:
        patch_text = f.read()

    ground_truth = set()
    for line in patch_text.split('\n'):
        m = re.match(r'^diff --git a/(\S+) b/\S+', line)
        if m:
            ground_truth.add(m.group(1))

    result = {'ground_truth_files': sorted(ground_truth)}

    for k in [1, 3, 5]:
        top_k = set(ranked_files[:k])
        inter = ground_truth & top_k
        denom = min(k, max(len(ranked_files), 1))
        result[f'precision_at_{k}'] = len(inter) / k if ranked_files else 0.0
        result[f'recall_at_{k}'] = (
            len(inter) / len(ground_truth) if ground_truth else 0.0
        )

    all_ranked = set(ranked_files)
    union = ground_truth | all_ranked
    inter = ground_truth & all_ranked
    result['file_iou'] = len(inter) / len(union) if union else 0.0

    return result


# ─── Main: build database + report ────────────────────────────────────

def main():
    # Parse all crash reports
    reports = {}
    crash_dir = '/app/data/crash_reports'
    for fname in sorted(os.listdir(crash_dir)):
        if fname.endswith('.txt'):
            crash_id = fname.replace('.txt', '')
            reports[crash_id] = parse_crash_report(
                os.path.join(crash_dir, fname)
            )

    # Create SQLite database from schema
    if os.path.exists('/app/crash_triage.db'):
        os.remove('/app/crash_triage.db')

    conn = sqlite3.connect('/app/crash_triage.db')
    with open('/app/reference/schema.sql', 'r') as f:
        conn.executescript(f.read())

    # Populate crashes table
    for crash_id, r in reports.items():
        conn.execute(
            "INSERT INTO crashes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                crash_id,
                r['bug_type'],
                r['access_type'],
                r['access_size'],
                r['faulting_function'],
                r['task_comm'],
                r['task_pid'],
                r['kernel_version'],
                json.dumps(r['call_trace']),
            )
        )

    # Deduplication
    groups = deduplicate(reports)

    for gid, group in enumerate(groups):
        for crash_id in group:
            conn.execute(
                "INSERT INTO dedup_groups VALUES (?, ?)",
                (gid, crash_id)
            )

    # Multi-trial evaluation
    receipt_paths = [
        '/app/data/receipts/receipt_1.json',
        '/app/data/receipts/receipt_2.json',
        '/app/data/receipts/receipt_3.json',
    ]
    eval_result = process_receipts(receipt_paths)

    for bug_id, clean_count, total_trials in eval_result['resolved']:
        conn.execute(
            "INSERT INTO evaluations VALUES (?, ?, ?, ?)",
            (bug_id, 'resolved', clean_count, total_trials)
        )
    for bug_id, clean_count, total_trials in eval_result['unresolved']:
        conn.execute(
            "INSERT INTO evaluations VALUES (?, ?, ?, ?)",
            (bug_id, 'unresolved', clean_count, total_trials)
        )

    conn.commit()
    conn.close()

    # Localization
    ranked = [
        'net/core/sock.c',
        'net/ipv4/tcp.c',
        'net/core/filter.c',
        'mm/slub.c',
        'fs/ext4/inode.c',
    ]
    loc = compute_localization(
        '/app/data/patches/patch_net_sock.patch', ranked
    )

    # Write JSON report
    os.makedirs('/app/output', exist_ok=True)
    report = {
        'crash_groups': groups,
        'evaluation': {
            'resolved': sorted([x[0] for x in eval_result['resolved']]),
            'unresolved': sorted([x[0] for x in eval_result['unresolved']]),
            'resolution_count': len(eval_result['resolved']),
        },
        'localization': {
            'precision_at_1': loc['precision_at_1'],
            'precision_at_3': loc['precision_at_3'],
            'precision_at_5': loc['precision_at_5'],
            'recall_at_1': loc['recall_at_1'],
            'recall_at_3': loc['recall_at_3'],
            'recall_at_5': loc['recall_at_5'],
            'file_iou': loc['file_iou'],
        },
    }

    with open('/app/output/triage_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Triage complete. Database: /app/crash_triage.db, "
          "Report: /app/output/triage_report.json")


if __name__ == '__main__':
    main()
