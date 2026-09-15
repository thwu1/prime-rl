#!/usr/bin/env python3
"""
Solve the warehouse data recovery, view evaluation, and schema hardening task.
"""
import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone


def main():
    os.makedirs('/app/output', exist_ok=True)
    conn = sqlite3.connect('/data/warehouse.db')
    c = conn.cursor()

    # ================================================================
    # 1. LOAD SUPPLIER RATE CARD FROM CSV
    # ================================================================
    supplier_rates = {}
    with open('/data/supplier_rates.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['active'].strip().lower() == 'true':
                sku = row['sku'].strip()
                rate = float(row['contracted_rate'].strip())
                date = row['effective_date'].strip()
                if sku not in supplier_rates or date > supplier_rates[sku][1]:
                    supplier_rates[sku] = (rate, date)

    # ================================================================
    # 2. TYPE VIOLATIONS
    # ================================================================
    type_violations = []

    c.execute(
        "SELECT id, unit_cost, typeof(unit_cost) FROM parts "
        "WHERE typeof(unit_cost) NOT IN ('real', 'integer', 'null')")
    for pid, val, typ in c.fetchall():
        type_violations.append({
            'table': 'parts', 'column': 'unit_cost', 'rowid': pid,
            'value': str(val), 'expected_type': 'real', 'actual_type': typ})

    for col in ('parent_id', 'child_id', 'quantity'):
        c.execute(
            f"SELECT rowid, {col}, typeof({col}) FROM bom_edges "
            f"WHERE typeof({col}) != 'integer'")
        for rid, val, typ in c.fetchall():
            type_violations.append({
                'table': 'bom_edges', 'column': col, 'rowid': rid,
                'value': str(val), 'expected_type': 'integer',
                'actual_type': typ})

    c.execute(
        "SELECT id, part_id, typeof(part_id) FROM inventory "
        "WHERE typeof(part_id) != 'integer'")
    for iid, val, typ in c.fetchall():
        type_violations.append({
            'table': 'inventory', 'column': 'part_id', 'rowid': iid,
            'value': str(val), 'expected_type': 'integer',
            'actual_type': typ})

    # ================================================================
    # 3. RESOLVE UNIT COSTS
    # ================================================================
    c.execute("SELECT id, sku FROM parts")
    id_to_sku = {row[0]: row[1] for row in c.fetchall()}

    costs = {}
    c.execute("SELECT id, sku, unit_cost, typeof(unit_cost) FROM parts")
    for pid, sku, cost, typ in c.fetchall():
        if typ in ('real', 'integer'):
            costs[pid] = float(cost)
        elif typ == 'text' and cost:
            cleaned = cost.strip().lstrip('$').replace(',', '')
            try:
                costs[pid] = float(cleaned)
            except ValueError:
                if sku in supplier_rates:
                    costs[pid] = supplier_rates[sku][0]
                else:
                    costs[pid] = 0.0
        else:
            costs[pid] = 0.0

    # ================================================================
    # 4. LOAD BOM GRAPH
    # ================================================================
    c.execute(
        "SELECT CAST(parent_id AS INTEGER), "
        "       CAST(child_id AS INTEGER), "
        "       CAST(quantity AS INTEGER) "
        "FROM bom_edges")
    children = {}
    for parent, child, qty in c.fetchall():
        children.setdefault(parent, []).append((child, qty))

    # ================================================================
    # 5. CYCLE DETECTION
    # ================================================================
    all_nodes = set(children.keys())
    for cs in children.values():
        for cid, _ in cs:
            all_nodes.add(cid)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in all_nodes}
    back_edges = set()
    cycles_found = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for child, _ in children.get(node, []):
            if color.get(child, WHITE) == GRAY:
                back_edges.add((node, child))
                idx = path.index(child)
                cycles_found.append(path[idx:] + [child])
            elif color.get(child, WHITE) == WHITE:
                dfs(child, path)
        path.pop()
        color[node] = BLACK

    for node in sorted(all_nodes):
        if color[node] == WHITE:
            dfs(node, [])

    unique_cycles = []
    seen_cycle_keys = set()
    for cyc in cycles_found:
        key = frozenset(cyc)
        if key not in seen_cycle_keys:
            seen_cycle_keys.add(key)
            unique_cycles.append(cyc)

    # ================================================================
    # 6. RECURSIVE BOM COSTS
    # ================================================================
    memo = {}

    def compute_cost(part_id):
        if part_id in memo:
            return memo[part_id]
        base = costs.get(part_id, 0.0)
        total = base
        for child_id, qty in children.get(part_id, []):
            if (part_id, child_id) not in back_edges:
                total += qty * compute_cost(child_id)
        memo[part_id] = total
        return total

    c.execute("SELECT id, sku FROM parts WHERE category = 'assembly' ORDER BY sku")
    assemblies = c.fetchall()

    with open('/app/output/bom_costs.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['sku', 'total_cost'])
        for aid, asku in assemblies:
            w.writerow([asku, f'{compute_cost(aid):.2f}'])

    # ================================================================
    # 7. INVENTORY VALUATION
    # ================================================================
    c.execute(
        "SELECT CAST(part_id AS INTEGER), warehouse, qty_on_hand "
        "FROM inventory")
    wh_totals = {}
    for pid, wh, qty in c.fetchall():
        unit = costs.get(pid, 0.0)
        wh_totals[wh] = wh_totals.get(wh, 0.0) + qty * unit

    with open('/app/output/valuation.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['warehouse', 'total_value'])
        for wh in sorted(wh_totals):
            w.writerow([wh, f'{wh_totals[wh]:.2f}'])

    # ================================================================
    # 8. MALFORMED JSON
    # ================================================================
    malformed = []
    c.execute("SELECT id, specs FROM parts WHERE specs IS NOT NULL")
    for pid, specs in c.fetchall():
        try:
            json.loads(specs)
        except json.JSONDecodeError as e:
            malformed.append({'part_id': pid, 'issue': str(e)})

    # ================================================================
    # 9. DATE ANOMALIES
    # ================================================================
    date_anomalies = []
    c.execute("SELECT id, last_audit FROM inventory WHERE last_audit IS NOT NULL")
    for iid, raw in c.fetchall():
        if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
            continue
        normalized = None
        if re.match(r'^\d{9,}$', raw):
            dt = datetime.fromtimestamp(int(raw), tz=timezone.utc)
            normalized = dt.strftime('%Y-%m-%d')
        elif re.match(r'^\d{2}/\d{2}/\d{4}$', raw):
            parts_d = raw.split('/')
            normalized = f'{parts_d[2]}-{parts_d[0]}-{parts_d[1]}'
        if normalized:
            date_anomalies.append({
                'inventory_id': iid,
                'raw_value': raw,
                'normalized_iso': normalized})

    # ================================================================
    # 10. WRITE AUDIT REPORT
    # ================================================================
    audit = {
        'type_violations': type_violations,
        'cycles': unique_cycles,
        'malformed_json': malformed,
        'date_anomalies': date_anomalies,
    }
    with open('/app/output/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    # ================================================================
    # 11. VIEW EVALUATION
    # ================================================================
    view_evaluation = [
        {
            "view_name": "v_inventory_value",
            "diagnosis": (
                "Produces zero or incorrect line_value for parts with TEXT-type "
                "unit_cost values. Costs stored as '$4.00' or '$11.00' silently "
                "evaluate to 0 in arithmetic because SQLite cannot implicitly "
                "convert strings with '$' prefix to numeric. The indeterminate "
                "cost 'TBD' also evaluates to 0. This causes significant "
                "underreporting of inventory value for affected warehouses."
            ),
            "root_cause": (
                "The unit_cost column in parts has no declared type (NONE "
                "affinity), allowing TEXT values like '$4.00' and 'TBD' to be "
                "stored without error. SQLite's arithmetic operators attempt "
                "TEXT-to-REAL coercion but fail for strings with non-numeric "
                "characters such as '$', silently producing 0 instead of "
                "raising an error. Additionally, inventory.part_id has NONE "
                "affinity, storing TEXT '10' which relies on implicit affinity "
                "conversion in JOINs with INTEGER-affinity columns."
            ),
            "severity": "critical",
            "corrected_sql": (
                "CREATE VIEW v_inventory_value_corrected AS "
                "SELECT i.id, p.sku, i.warehouse, i.qty_on_hand, "
                "CASE WHEN typeof(p.unit_cost) IN ('real','integer') "
                "THEN p.unit_cost "
                "WHEN typeof(p.unit_cost) = 'text' "
                "THEN CAST(REPLACE(REPLACE(p.unit_cost,'$',''),',','') AS REAL) "
                "ELSE 0 END AS unit_cost, "
                "i.qty_on_hand * CASE WHEN typeof(p.unit_cost) IN ('real','integer') "
                "THEN p.unit_cost "
                "WHEN typeof(p.unit_cost) = 'text' "
                "THEN CAST(REPLACE(REPLACE(p.unit_cost,'$',''),',','') AS REAL) "
                "ELSE 0 END AS line_value "
                "FROM inventory i "
                "JOIN parts p ON CAST(i.part_id AS INTEGER) = p.id"
            )
        },
        {
            "view_name": "v_bom_summary",
            "diagnosis": (
                "Includes cycle-forming edges (15->4 and 11->5) that make the "
                "BOM directed graph cyclic, preventing correct recursive cost "
                "computation. Also relies on implicit affinity conversion for "
                "the TEXT parent_id='2' row, which happens to work in this JOIN "
                "context but is fragile and would fail in standalone WHERE "
                "clauses on the NONE-affinity column."
            ),
            "root_cause": (
                "The bom_edges table declares no column types on parent_id, "
                "child_id, and quantity (NONE affinity). TEXT values are stored "
                "without constraint violation. While JOINs against parts.id "
                "(INTEGER PRIMARY KEY, INTEGER affinity) trigger implicit "
                "affinity conversion that converts TEXT '2' to INTEGER 2, this "
                "behavior is non-obvious and would not apply in standalone "
                "WHERE clauses on the NONE-affinity column itself. The view "
                "also lacks any mechanism to detect or exclude BOM cycles."
            ),
            "severity": "warning",
            "corrected_sql": (
                "CREATE VIEW v_bom_summary_corrected AS "
                "SELECT p.sku AS parent_sku, c.sku AS child_sku, "
                "CAST(be.quantity AS INTEGER) AS quantity "
                "FROM parts p "
                "JOIN bom_edges be ON p.id = CAST(be.parent_id AS INTEGER) "
                "JOIN parts c ON CAST(be.child_id AS INTEGER) = c.id"
            )
        }
    ]

    with open('/app/output/view_evaluation.json', 'w') as f:
        json.dump(view_evaluation, f, indent=2)

    # ================================================================
    # 12. HARDENED DATABASE
    # ================================================================
    hdb_path = '/app/output/warehouse_hardened.db'
    if os.path.exists(hdb_path):
        os.remove(hdb_path)

    hconn = sqlite3.connect(hdb_path)
    hc = hconn.cursor()

    # Create STRICT tables with proper types, FK, and CHECK constraints
    hc.execute('''CREATE TABLE parts (
        id INTEGER PRIMARY KEY,
        sku TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        unit_cost REAL NOT NULL CHECK(unit_cost >= 0.0),
        category TEXT NOT NULL,
        specs TEXT
    ) STRICT''')

    hc.execute('''CREATE TABLE bom_edges (
        parent_id INTEGER NOT NULL REFERENCES parts(id),
        child_id INTEGER NOT NULL REFERENCES parts(id),
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        PRIMARY KEY (parent_id, child_id)
    ) STRICT''')

    hc.execute('''CREATE TABLE inventory (
        id INTEGER PRIMARY KEY,
        part_id INTEGER NOT NULL REFERENCES parts(id),
        warehouse TEXT NOT NULL,
        qty_on_hand INTEGER NOT NULL CHECK(qty_on_hand >= 0),
        last_audit TEXT
    ) STRICT''')

    hc.execute('''CREATE TABLE purchase_history (
        id INTEGER PRIMARY KEY,
        part_id INTEGER NOT NULL REFERENCES parts(id),
        supplier TEXT NOT NULL,
        unit_price REAL NOT NULL CHECK(unit_price >= 0.0),
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        order_date TEXT NOT NULL
    ) STRICT''')

    hc.execute('''CREATE TABLE schema_docs (
        table_name TEXT NOT NULL,
        column_name TEXT NOT NULL,
        intended_type TEXT NOT NULL,
        description TEXT
    ) STRICT''')

    hc.execute('''CREATE TABLE business_rules (
        rule_id INTEGER PRIMARY KEY,
        domain TEXT NOT NULL,
        rule_text TEXT NOT NULL
    ) STRICT''')

    hconn.commit()

    # Enable foreign keys for data insertion
    hconn.execute("PRAGMA foreign_keys = ON")

    # Migrate parts with resolved costs
    c.execute("SELECT id, sku, name, category, specs FROM parts ORDER BY id")
    for pid, sku, name, cat, specs in c.fetchall():
        resolved = float(costs.get(pid, 0.0))
        hc.execute("INSERT INTO parts VALUES (?,?,?,?,?,?)",
                   (pid, sku, name, resolved, cat, specs))

    # Migrate valid BOM edges (exclude cycle back-edges)
    c.execute(
        "SELECT CAST(parent_id AS INTEGER), CAST(child_id AS INTEGER), "
        "CAST(quantity AS INTEGER) FROM bom_edges")
    for parent, child, qty in c.fetchall():
        if (parent, child) not in back_edges:
            hc.execute("INSERT INTO bom_edges VALUES (?,?,?)",
                       (int(parent), int(child), int(qty)))

    # Migrate inventory with resolved types and normalized dates
    c.execute(
        "SELECT id, CAST(part_id AS INTEGER), warehouse, qty_on_hand, "
        "last_audit FROM inventory ORDER BY id")
    for iid, pid, wh, qty, audit_date in c.fetchall():
        norm_date = audit_date
        if audit_date and re.match(r'^\d{2}/\d{2}/\d{4}$', audit_date):
            parts_d = audit_date.split('/')
            norm_date = f'{parts_d[2]}-{parts_d[0]}-{parts_d[1]}'
        elif audit_date and re.match(r'^\d{9,}$', audit_date):
            dt = datetime.fromtimestamp(int(audit_date), tz=timezone.utc)
            norm_date = dt.strftime('%Y-%m-%d')
        hc.execute("INSERT INTO inventory VALUES (?,?,?,?,?)",
                   (int(iid), int(pid), wh, int(qty), norm_date))

    # Migrate purchase history
    c.execute(
        "SELECT id, part_id, supplier, unit_price, quantity, order_date "
        "FROM purchase_history ORDER BY id")
    for row in c.fetchall():
        hc.execute("INSERT INTO purchase_history VALUES (?,?,?,?,?,?)", row)

    # Migrate metadata tables
    c.execute("SELECT * FROM schema_docs")
    for row in c.fetchall():
        hc.execute("INSERT INTO schema_docs VALUES (?,?,?,?)", row)

    c.execute("SELECT * FROM business_rules")
    for row in c.fetchall():
        hc.execute("INSERT INTO business_rules VALUES (?,?,?)", row)

    # Create corrected views in hardened DB (simple SQL since types are now clean)
    hc.execute('''CREATE VIEW v_inventory_value AS
        SELECT i.id, p.sku, i.warehouse, i.qty_on_hand, p.unit_cost,
               i.qty_on_hand * p.unit_cost AS line_value
        FROM inventory i
        JOIN parts p ON i.part_id = p.id''')

    hc.execute('''CREATE VIEW v_bom_summary AS
        SELECT p.sku AS parent_sku, c.sku AS child_sku, be.quantity
        FROM parts p
        JOIN bom_edges be ON p.id = be.parent_id
        JOIN parts c ON be.child_id = c.id''')

    hconn.commit()
    hconn.close()
    conn.close()


if __name__ == '__main__':
    main()
