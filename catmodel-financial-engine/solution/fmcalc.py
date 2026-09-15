#!/usr/bin/env python3
"""
Catastrophe model financial module pipeline engine with SQLite backend.

Loads ground-up losses, applies insurance financial terms through a multi-level
hierarchical aggregation structure with proportional back-allocation, stores
intermediate and final results in SQLite, and exports to CSV and JSON.

"""

import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict

DB_PATH = '/app/fm_results.db'
DATA_DIR = '/app/data'
OUTPUT_CSV = '/app/output.csv'
REPORT_JSON = '/app/report.json'


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def apply_calcrule(calcrule_id, params, input_loss):
    ded1 = params['deductible1']
    att1 = params['attachment1']
    lim1 = params['limit1']
    sh1 = params['share1']

    if calcrule_id == 1:
        loss = input_loss - ded1
        if loss < 0:
            loss = 0.0
        if loss > lim1:
            loss = lim1
        return loss
    elif calcrule_id == 2:
        loss = input_loss - ded1
        if loss < 0:
            loss = 0.0
        if loss > att1 + lim1:
            loss = lim1
        else:
            loss = loss - att1
        if loss < 0:
            loss = 0.0
        loss = loss * sh1
        return loss
    elif calcrule_id == 3:
        if input_loss <= ded1:
            return 0.0
        loss = input_loss
        if loss > lim1:
            loss = lim1
        return loss
    elif calcrule_id == 5:
        if ded1 + lim1 >= 1.0:
            return input_loss * (1.0 - ded1)
        else:
            return input_loss * lim1
    elif calcrule_id == 9:
        effective_ded = ded1 * lim1
        loss = input_loss - effective_ded
        if loss < 0:
            loss = 0.0
        if loss > lim1:
            loss = lim1
        return loss
    elif calcrule_id == 12:
        return max(input_loss - ded1, 0.0)
    elif calcrule_id == 14:
        return min(input_loss, lim1)
    elif calcrule_id == 16:
        loss = input_loss * (1.0 - ded1)
        if loss < 0:
            loss = 0.0
        return loss
    elif calcrule_id == 100:
        return input_loss
    else:
        raise ValueError(f"Unsupported calcrule_id: {calcrule_id}")


def do_load():
    """Create database, load input CSVs, define schema."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Input data tables
    c.execute('''CREATE TABLE gul_losses (
        event_id INTEGER, item_id INTEGER, sidx INTEGER, loss REAL
    )''')
    c.execute('''CREATE TABLE programme (
        from_agg_id INTEGER, level_id INTEGER, to_agg_id INTEGER
    )''')
    c.execute('''CREATE TABLE profiles (
        profile_id INTEGER, calcrule_id INTEGER,
        deductible1 REAL, deductible2 REAL, deductible3 REAL,
        attachment1 REAL, limit1 REAL, share1 REAL, share2 REAL, share3 REAL
    )''')
    c.execute('''CREATE TABLE policytc (
        layer_id INTEGER, level_id INTEGER, agg_id INTEGER, profile_id INTEGER
    )''')

    # Computed results tables
    c.execute('''CREATE TABLE level_losses (
        event_id INTEGER, sidx INTEGER, level INTEGER, agg_id INTEGER,
        input_loss REAL, output_loss REAL
    )''')
    c.execute('''CREATE TABLE final_losses (
        event_id INTEGER, item_id INTEGER, sidx INTEGER, loss REAL
    )''')

    # Event summary view
    c.execute('''CREATE VIEW event_summary AS
        SELECT
            g.event_id,
            g.total_gul,
            COALESCE(f.total_insured, 0.0) AS total_insured,
            COALESCE(f.item_count, 0) AS item_count,
            ROUND(100.0 * (1.0 - COALESCE(f.total_insured, 0.0) / g.total_gul), 2) AS reduction_pct
        FROM (
            SELECT event_id, SUM(loss) AS total_gul
            FROM gul_losses
            GROUP BY event_id
        ) g
        LEFT JOIN (
            SELECT event_id,
                   SUM(loss) AS total_insured,
                   COUNT(DISTINCT item_id) AS item_count
            FROM final_losses
            WHERE loss > 0
            GROUP BY event_id
        ) f ON g.event_id = f.event_id
        ORDER BY g.event_id
    ''')

    # Load programme
    for row in load_csv(f'{DATA_DIR}/fm_programme.csv'):
        c.execute('INSERT INTO programme VALUES (?,?,?)',
                  (int(row['from_agg_id']), int(row['level_id']), int(row['to_agg_id'])))

    # Load profiles
    for row in load_csv(f'{DATA_DIR}/fm_profile.csv'):
        c.execute('INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (int(row['profile_id']), int(row['calcrule_id']),
                   float(row['deductible1']), float(row['deductible2']),
                   float(row['deductible3']), float(row['attachment1']),
                   float(row['limit1']), float(row['share1']),
                   float(row['share2']), float(row['share3'])))

    # Load policytc
    for row in load_csv(f'{DATA_DIR}/fm_policytc.csv'):
        c.execute('INSERT INTO policytc VALUES (?,?,?,?)',
                  (int(row['layer_id']), int(row['level_id']),
                   int(row['agg_id']), int(row['profile_id'])))

    # Load GULs
    for row in load_csv(f'{DATA_DIR}/guls.csv'):
        c.execute('INSERT INTO gul_losses VALUES (?,?,?,?)',
                  (int(row['event_id']), int(row['item_id']),
                   int(row['sidx']), float(row['loss'])))

    conn.commit()
    conn.close()


def do_compute():
    """Compute hierarchical losses and store in database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Read hierarchy
    hierarchy = defaultdict(dict)
    for row in c.execute('SELECT from_agg_id, level_id, to_agg_id FROM programme'):
        hierarchy[row[1]][row[0]] = row[2]
    max_level = max(hierarchy.keys())

    # Build profile lookup
    profile_map = {}
    for row in c.execute('SELECT profile_id, calcrule_id, deductible1, attachment1, limit1, share1 FROM profiles'):
        profile_map[row[0]] = {
            'calcrule_id': row[1], 'deductible1': row[2],
            'attachment1': row[3], 'limit1': row[4], 'share1': row[5]
        }

    # Build node profile: (level, agg_id) -> profile params
    node_profile = {}
    for row in c.execute('SELECT level_id, agg_id, profile_id FROM policytc'):
        node_profile[(row[0], row[1])] = profile_map[row[2]]

    # Read GULs
    gul_data = defaultdict(dict)
    all_items = set()
    for row in c.execute('SELECT event_id, item_id, sidx, loss FROM gul_losses'):
        gul_data[(row[0], row[2])][row[1]] = row[3]
        all_items.add(row[1])
    all_items = sorted(all_items)

    # Build reverse maps: level -> {to_agg_id -> [from_agg_ids]}
    level_nodes = {}
    for level in range(1, max_level + 1):
        nodes = defaultdict(list)
        for fid, tid in hierarchy[level].items():
            nodes[tid].append(fid)
        level_nodes[level] = dict(nodes)

    # Descendant cache
    desc_cache = {}

    def get_descendants(level, children):
        key = (level, tuple(sorted(children)))
        if key in desc_cache:
            return desc_cache[key]
        current = set(children)
        for lev in range(level - 1, 0, -1):
            prev = set()
            for fid, tid in hierarchy[lev].items():
                if tid in current:
                    prev.add(fid)
            current = prev
        result = sorted(i for i in current if i in all_items)
        desc_cache[key] = result
        return result

    # Clear previous computed results
    c.execute('DELETE FROM level_losses')
    c.execute('DELETE FROM final_losses')

    level_losses_rows = []
    final_losses_rows = []

    for (eid, sid) in sorted(gul_data.keys()):
        gul_map = gul_data[(eid, sid)]
        item_loss = {iid: gul_map.get(iid, 0.0) for iid in all_items}

        for level in range(1, max_level + 1):
            nodes = level_nodes.get(level, {})
            for node_id, children in nodes.items():
                desc = get_descendants(level, children)
                agg_input = sum(item_loss[iid] for iid in desc)

                p = node_profile[(level, node_id)]
                agg_output = apply_calcrule(p['calcrule_id'], p, agg_input)

                level_losses_rows.append(
                    (eid, sid, level, node_id, agg_input, agg_output))

                if agg_input > 0:
                    factor = agg_output / agg_input
                else:
                    factor = 0.0

                for iid in desc:
                    item_loss[iid] *= factor

        for iid in all_items:
            rounded = round(item_loss[iid], 2)
            if rounded > 0:
                final_losses_rows.append((eid, iid, sid, rounded))

    c.executemany('INSERT INTO level_losses VALUES (?,?,?,?,?,?)',
                  level_losses_rows)
    c.executemany('INSERT INTO final_losses VALUES (?,?,?,?)',
                  final_losses_rows)

    conn.commit()
    conn.close()


def do_export():
    """Export final_losses from SQLite to output.csv."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        'SELECT event_id, item_id, sidx, loss FROM final_losses '
        'ORDER BY event_id, item_id, sidx'
    ).fetchall()
    conn.close()

    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['event_id', 'item_id', 'sidx', 'loss'])
        for row in rows:
            writer.writerow(row)


def do_report():
    """Query event_summary view and write report.json."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        'SELECT event_id, total_gul, total_insured, item_count, reduction_pct '
        'FROM event_summary ORDER BY event_id'
    ).fetchall()
    conn.close()

    report = []
    for r in rows:
        report.append({
            'event_id': r[0],
            'total_gul': r[1],
            'total_insured': r[2],
            'item_count': r[3],
            'reduction_pct': r[4]
        })

    with open(REPORT_JSON, 'w') as f:
        json.dump(report, f, indent=2)


def do_all():
    """Run the full pipeline: load → compute → export → report."""
    do_load()
    do_compute()
    do_export()
    do_report()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    commands = {
        'load': do_load,
        'compute': do_compute,
        'export': do_export,
        'report': do_report,
        'all': do_all,
    }
    if cmd not in commands:
        print(f"Unknown command: {cmd}. Use: {', '.join(commands.keys())}",
              file=sys.stderr)
        sys.exit(1)
    commands[cmd]()
