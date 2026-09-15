#!/usr/bin/env python3
"""Crash recovery implementation for a double-crash WAL scenario."""

import sqlite3
import json
import struct
import os

WAL_DB = '/app/wal.db'
CRASH_STATE = '/app/diagnostics/crash_state.json'
PAGES_BIN = '/app/pages.bin'
OUTPUT_FILE = '/app/recovery_output.json'


def load_wal():
    """Read WAL records, checkpoint data, and master record from SQLite."""
    conn = sqlite3.connect(WAL_DB)
    conn.row_factory = sqlite3.Row

    records = [dict(r) for r in conn.execute('SELECT * FROM log_records ORDER BY lsn')]
    ckpt = [dict(r) for r in conn.execute('SELECT * FROM checkpoint_data')]
    master_lsn = conn.execute(
        'SELECT checkpoint_lsn FROM master_record'
    ).fetchone()['checkpoint_lsn']

    conn.close()
    return records, ckpt, master_lsn


def load_page_baselines():
    """Parse the binary page store to extract initial page values."""
    baselines = {}
    with open(PAGES_BIN, 'rb') as f:
        magic = f.read(4)
        assert magic == b'PGST', f"Invalid page store magic: {magic}"
        version = struct.unpack('<H', f.read(2))[0]
        n_entries = struct.unpack('<H', f.read(2))[0]
        for _ in range(n_entries):
            page_id = struct.unpack('<I', f.read(4))[0]
            init_val = struct.unpack('<i', f.read(4))[0]
            _table = f.read(32)   # table_name (skip)
            _desc = f.read(64)    # description (skip)
            baselines[page_id] = init_val
    return baselines


def load_flushed_pages():
    """Extract flushed page map from the crash state report."""
    with open(CRASH_STATE) as f:
        data = json.load(f)
    entries = data['crash_report']['system_state_at_crash']['disk_manager']['flushed_pages']
    return {e['page_id']: e['on_disk_page_lsn'] for e in entries}


# ---------------------------------------------------------------------------
# Analysis phase
# ---------------------------------------------------------------------------

def analysis_phase(records, ckpt_data, master_lsn):
    dpt = {}           # page_id -> recLSN
    txn_table = {}     # txn_id -> {status, last_lsn}
    ended_txns = set()

    for rec in records:
        if rec['lsn'] < master_lsn:
            continue

        rt = rec['record_type']
        txn = rec['txn_id']

        if rt == 'CHECKPOINT_BEGIN':
            continue

        if rt == 'CHECKPOINT_END':
            for entry in ckpt_data:
                if entry['data_type'] == 'DPT':
                    dpt[entry['entry_key']] = entry['rec_lsn']
                elif entry['data_type'] == 'TXN_TABLE':
                    tid = entry['entry_key']
                    if tid in ended_txns:
                        continue
                    if tid not in txn_table:
                        txn_table[tid] = {
                            'status': entry['status'],
                            'last_lsn': entry['last_lsn'],
                        }
                    else:
                        if entry['last_lsn'] >= txn_table[tid]['last_lsn']:
                            txn_table[tid]['last_lsn'] = entry['last_lsn']
                        order = {'RUNNING': 0, 'COMMITTING': 1, 'ABORTING': 1,
                                 'RECOVERY_ABORTING': 1, 'COMPLETE': 2}
                        if order.get(entry['status'], 0) > order.get(txn_table[tid]['status'], 0):
                            s = entry['status']
                            if s == 'ABORTING':
                                s = 'RECOVERY_ABORTING'
                            txn_table[tid]['status'] = s
            continue

        if txn is None:
            continue

        if rt == 'BEGIN':
            txn_table[txn] = {'status': 'RUNNING', 'last_lsn': rec['lsn']}

        elif rt == 'UPDATE':
            if txn not in txn_table:
                txn_table[txn] = {'status': 'RUNNING', 'last_lsn': rec['lsn']}
            else:
                txn_table[txn]['last_lsn'] = rec['lsn']
            pid = rec['page_id']
            if pid is not None and pid not in dpt:
                dpt[pid] = rec['lsn']

        elif rt == 'CLR':
            if txn not in txn_table:
                txn_table[txn] = {'status': 'RECOVERY_ABORTING', 'last_lsn': rec['lsn']}
            else:
                txn_table[txn]['last_lsn'] = rec['lsn']
                txn_table[txn]['status'] = 'RECOVERY_ABORTING'
            pid = rec['page_id']
            if pid is not None and pid not in dpt:
                dpt[pid] = rec['lsn']

        elif rt == 'NTA_COMPLETE':
            if txn in txn_table:
                txn_table[txn]['last_lsn'] = rec['lsn']

        elif rt == 'COMMIT':
            if txn not in txn_table:
                txn_table[txn] = {'status': 'COMMITTING', 'last_lsn': rec['lsn']}
            else:
                txn_table[txn]['status'] = 'COMMITTING'
                txn_table[txn]['last_lsn'] = rec['lsn']

        elif rt == 'ABORT':
            if txn not in txn_table:
                txn_table[txn] = {'status': 'RECOVERY_ABORTING', 'last_lsn': rec['lsn']}
            else:
                txn_table[txn]['status'] = 'RECOVERY_ABORTING'
                txn_table[txn]['last_lsn'] = rec['lsn']

        elif rt == 'END':
            ended_txns.add(txn)
            if txn in txn_table:
                del txn_table[txn]

    for txn in txn_table:
        if txn_table[txn]['status'] == 'RUNNING':
            txn_table[txn]['status'] = 'RECOVERY_ABORTING'

    return dpt, txn_table


# ---------------------------------------------------------------------------
# Redo phase
# ---------------------------------------------------------------------------

def redo_phase(records, dpt, flushed_pages, page_states):
    if not dpt:
        return []

    min_rec_lsn = min(dpt.values())
    redo_lsns = []

    for rec in records:
        if rec['lsn'] < min_rec_lsn:
            continue
        if rec['record_type'] not in ('UPDATE', 'CLR'):
            continue

        pid = rec['page_id']
        if pid is None or pid not in dpt:
            continue
        if rec['lsn'] < dpt[pid]:
            continue

        on_disk_lsn = flushed_pages.get(pid, -1)
        if rec['lsn'] <= on_disk_lsn:
            continue

        page_states[pid] = rec['after_value']
        redo_lsns.append(rec['lsn'])

    return redo_lsns


# ---------------------------------------------------------------------------
# Undo phase
# ---------------------------------------------------------------------------

def undo_phase(records, txn_table, page_states):
    lsn_map = {r['lsn']: r for r in records}
    undo_lsns = []

    to_undo = {}
    for txn, info in txn_table.items():
        if info['status'] == 'RECOVERY_ABORTING':
            to_undo[txn] = info['last_lsn']

    while to_undo:
        max_txn = max(to_undo, key=lambda t: to_undo[t])
        lsn = to_undo[max_txn]
        rec = lsn_map[lsn]
        rt = rec['record_type']

        if rt in ('CLR', 'NTA_COMPLETE'):
            nxt = rec['undo_next_lsn']
            if nxt is None or nxt == 0:
                del to_undo[max_txn]
            else:
                to_undo[max_txn] = nxt

        elif rt == 'UPDATE':
            page_states[rec['page_id']] = rec['before_value']
            undo_lsns.append(lsn)
            nxt = rec['prev_lsn']
            if nxt is None or nxt == 0:
                del to_undo[max_txn]
            else:
                to_undo[max_txn] = nxt

        elif rt == 'BEGIN':
            del to_undo[max_txn]

        else:
            nxt = rec['prev_lsn']
            if nxt is None or nxt == 0:
                del to_undo[max_txn]
            else:
                to_undo[max_txn] = nxt

    return undo_lsns


# ---------------------------------------------------------------------------
# NTA-protected page detection
# ---------------------------------------------------------------------------

def find_nta_protected_pages(records, aborted_txns):
    """Identify pages whose modifications persisted due to NTA protection."""
    protected = set()
    for rec in records:
        if rec['record_type'] == 'NTA_COMPLETE' and rec['txn_id'] in aborted_txns:
            undo_next = rec['undo_next_lsn']
            nta_lsn = rec['lsn']
            for r in records:
                if (r['txn_id'] == rec['txn_id']
                        and r['record_type'] == 'UPDATE'
                        and r['lsn'] > undo_next
                        and r['lsn'] < nta_lsn):
                    protected.add(r['page_id'])
    return sorted(protected)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    records, ckpt_data, master_lsn = load_wal()
    baselines = load_page_baselines()
    flushed_pages = load_flushed_pages()

    # Compute on-disk page states
    page_states = dict(baselines)
    for rec in records:
        if rec['record_type'] in ('UPDATE', 'CLR') and rec['page_id'] is not None:
            pid = rec['page_id']
            if pid in flushed_pages and rec['lsn'] <= flushed_pages[pid]:
                page_states[pid] = rec['after_value']

    # Analysis
    dpt, txn_table = analysis_phase(records, ckpt_data, master_lsn)

    # Determine committed/aborted transactions
    committed = set()
    all_txns = set()
    for rec in records:
        if rec['txn_id'] is not None:
            all_txns.add(rec['txn_id'])
        if rec['record_type'] == 'COMMIT':
            committed.add(rec['txn_id'])
    aborted = set()
    for t in all_txns:
        if t not in committed:
            has_work = any(
                r['record_type'] in ('UPDATE', 'CLR', 'ABORT')
                for r in records if r['txn_id'] == t
            )
            if has_work:
                aborted.add(t)

    # Redo
    redo_lsns = redo_phase(records, dpt, flushed_pages, page_states)

    # Undo
    undo_lsns = undo_phase(records, txn_table, page_states)

    # NTA-protected pages
    nta_pages = find_nta_protected_pages(records, aborted)

    output = {
        'analysis_dpt': {str(k): v for k, v in sorted(dpt.items())},
        'analysis_txn_table': {str(k): v for k, v in sorted(txn_table.items())},
        'redo_lsns': redo_lsns,
        'undo_lsns': undo_lsns,
        'final_page_states': {str(k): v for k, v in sorted(page_states.items())},
        'committed_txns': sorted(committed),
        'aborted_txns': sorted(aborted),
        'nta_protected_pages': nta_pages,
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Recovery output written to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
