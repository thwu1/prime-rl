
import csv
import json
import os
import sqlite3

import pytest


def read_csv_rows(path):
    """Read CSV file and return list of dicts with stripped keys."""
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            cleaned = {k.strip(): v.strip() for k, v in row.items()}
            rows.append(cleaned)
        return rows


def parse_float(s):
    """Parse a float from string, return None on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_all_ints(obj):
    """Recursively extract all integer-like values from nested JSON structure."""
    results = []
    if isinstance(obj, int):
        results.append(obj)
    elif isinstance(obj, float) and obj == int(obj):
        results.append(int(obj))
    elif isinstance(obj, str):
        try:
            results.append(int(obj))
        except ValueError:
            pass
    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_all_ints(item))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(extract_all_ints(v))
    return results


# ---------- BOM COSTS ----------

class TestBOMCosts:
    def test_file_exists(self):
        assert os.path.exists('/app/output/bom_costs.csv'), \
            "bom_costs.csv not found in /app/output/"

    def test_has_two_assemblies(self):
        rows = read_csv_rows('/app/output/bom_costs.csv')
        skus = [r['sku'] for r in rows]
        assert 'ASM-A' in skus, "ASM-A missing from bom_costs.csv"
        assert 'ASM-B' in skus, "ASM-B missing from bom_costs.csv"

    def test_asm_a_cost(self):
        rows = read_csv_rows('/app/output/bom_costs.csv')
        asm_a = [r for r in rows if r['sku'] == 'ASM-A']
        assert len(asm_a) == 1, "Expected exactly one ASM-A row"
        cost = parse_float(asm_a[0]['total_cost'])
        assert cost is not None, "Could not parse ASM-A total_cost"
        assert abs(cost - 118.00) < 0.015, \
            f"ASM-A total cost should be 118.00, got {cost}"

    def test_asm_b_cost(self):
        rows = read_csv_rows('/app/output/bom_costs.csv')
        asm_b = [r for r in rows if r['sku'] == 'ASM-B']
        assert len(asm_b) == 1, "Expected exactly one ASM-B row"
        cost = parse_float(asm_b[0]['total_cost'])
        assert cost is not None, "Could not parse ASM-B total_cost"
        assert abs(cost - 76.00) < 0.015, \
            f"ASM-B total cost should be 76.00, got {cost}"


# ---------- INVENTORY VALUATION ----------

class TestValuation:
    def test_file_exists(self):
        assert os.path.exists('/app/output/valuation.csv'), \
            "valuation.csv not found in /app/output/"

    def test_east_valuation(self):
        rows = read_csv_rows('/app/output/valuation.csv')
        east = [r for r in rows if r['warehouse'] == 'EAST']
        assert len(east) == 1, "EAST warehouse not found in valuation.csv"
        val = parse_float(east[0]['total_value'])
        assert val is not None, "Could not parse EAST total_value"
        assert abs(val - 20570.00) < 0.015, \
            f"EAST valuation should be 20570.00, got {val}"

    def test_west_valuation(self):
        rows = read_csv_rows('/app/output/valuation.csv')
        west = [r for r in rows if r['warehouse'] == 'WEST']
        assert len(west) == 1, "WEST warehouse not found in valuation.csv"
        val = parse_float(west[0]['total_value'])
        assert val is not None, "Could not parse WEST total_value"
        assert abs(val - 6287.50) < 0.015, \
            f"WEST valuation should be 6287.50, got {val}"


# ---------- AUDIT REPORT ----------

class TestAudit:
    def _load_audit(self):
        with open('/app/output/audit.json') as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists('/app/output/audit.json'), \
            "audit.json not found in /app/output/"

    def test_has_required_keys(self):
        audit = self._load_audit()
        for key in ('type_violations', 'cycles', 'malformed_json', 'date_anomalies'):
            assert key in audit, f"audit.json missing key '{key}'"

    def test_type_violation_count(self):
        audit = self._load_audit()
        n = len(audit['type_violations'])
        assert n == 6, f"Expected 6 type violations, got {n}"

    def test_cycle_count(self):
        audit = self._load_audit()
        n = len(audit['cycles'])
        assert n == 2, f"Expected 2 cycles, got {n}"

    def test_cycle_nodes_present(self):
        """Both cycles involve nodes {4,15} and {5,11}."""
        audit = self._load_audit()
        all_ints = extract_all_ints(audit['cycles'])
        for node in (4, 5, 11, 15):
            assert node in all_ints, \
                f"Cycle node {node} not found in reported cycles"

    def test_malformed_json_count(self):
        audit = self._load_audit()
        n = len(audit['malformed_json'])
        assert n == 2, f"Expected 2 malformed JSON entries, got {n}"

    def test_date_anomaly_count(self):
        audit = self._load_audit()
        n = len(audit['date_anomalies'])
        assert n == 3, f"Expected 3 date anomalies, got {n}"


# ---------- HARDENED DATABASE ----------

class TestHardenedDB:
    DB_PATH = '/app/output/warehouse_hardened.db'

    def _connect(self):
        conn = sqlite3.connect(self.DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def test_file_exists(self):
        assert os.path.exists(self.DB_PATH), "warehouse_hardened.db not found"

    def test_parts_table_is_strict(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='parts'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "parts table not found in hardened DB"
        assert 'STRICT' in row[0].upper(), "parts table should use STRICT mode"

    def test_bom_edges_table_is_strict(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bom_edges'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "bom_edges table not found"
        assert 'STRICT' in row[0].upper(), "bom_edges should use STRICT mode"

    def test_inventory_table_is_strict(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='inventory'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "inventory table not found"
        assert 'STRICT' in row[0].upper(), "inventory should use STRICT mode"

    def test_foreign_key_declarations(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bom_edges'")
        sql = c.fetchone()[0].upper()
        conn.close()
        assert 'REFERENCES' in sql, "bom_edges should declare foreign key REFERENCES"

    def test_check_constraint_exists(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='parts'")
        sql = c.fetchone()[0].upper()
        conn.close()
        assert 'CHECK' in sql, "parts table should have CHECK constraints"

    def test_all_parts_migrated(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM parts")
        count = c.fetchone()[0]
        conn.close()
        assert count == 15, f"Expected 15 parts migrated, got {count}"

    def test_costs_are_numeric(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT id, typeof(unit_cost) FROM parts WHERE unit_cost IS NOT NULL")
        rows = c.fetchall()
        conn.close()
        for pid, typ in rows:
            assert typ in ('real', 'integer'), \
                f"Part {pid}: unit_cost type should be real/integer, got {typ}"

    def test_tbd_cost_resolved_from_supplier_card(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT unit_cost FROM parts WHERE sku='RAW-09'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "RAW-09 not found in hardened DB"
        assert abs(row[0] - 9.00) < 0.01, \
            f"RAW-09 cost should be 9.00 (from supplier rate card), got {row[0]}"

    def test_cycle_edges_excluded(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM bom_edges
                     WHERE (parent_id=15 AND child_id=4)
                        OR (parent_id=11 AND child_id=5)""")
        count = c.fetchone()[0]
        conn.close()
        assert count == 0, "Cycle-forming edges should be excluded"

    def test_valid_edge_count(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM bom_edges")
        count = c.fetchone()[0]
        conn.close()
        assert count == 17, f"Expected 17 valid BOM edges (19 total minus 2 cycles), got {count}"

    def test_corrected_views_exist(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='view'")
        views = [row[0] for row in c.fetchall()]
        conn.close()
        assert len(views) >= 2, f"Expected at least 2 corrected views, got {views}"

    def test_inventory_view_correct_east_total(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name LIKE '%inventor%'")
        view_row = c.fetchone()
        assert view_row is not None, "No inventory view found in hardened DB"
        c.execute(f"SELECT SUM(line_value) FROM [{view_row[0]}] WHERE warehouse='EAST'")
        total = c.fetchone()[0]
        conn.close()
        assert total is not None, "Inventory view EAST sum is NULL"
        assert abs(total - 20570.00) < 1.0, \
            f"EAST total from corrected inventory view should be ~20570.00, got {total}"


# ---------- VIEW EVALUATION ----------

class TestViewEvaluation:
    EVAL_PATH = '/app/output/view_evaluation.json'

    def _load(self):
        with open(self.EVAL_PATH) as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists(self.EVAL_PATH), "view_evaluation.json not found"

    def test_is_array_with_entries(self):
        data = self._load()
        assert isinstance(data, list), "view_evaluation.json should be a JSON array"
        assert len(data) >= 2, f"Expected at least 2 view evaluations, got {len(data)}"

    def test_inventory_view_identified(self):
        data = self._load()
        names = [str(e.get('view_name', '')).lower() for e in data]
        assert any('inventory' in n for n in names), \
            "No evaluation found for the inventory view"

    def test_inventory_defect_mentions_type_issue(self):
        data = self._load()
        inv = None
        for entry in data:
            if 'inventory' in str(entry.get('view_name', '')).lower():
                inv = entry
                break
        assert inv is not None
        combined = json.dumps(inv).lower()
        type_keywords = ['text', 'type', 'affinity', 'coercion', 'cast', 'storage class']
        assert any(kw in combined for kw in type_keywords), \
            "Inventory view evaluation should identify type-related root cause"

    def test_severity_ratings_present(self):
        data = self._load()
        for entry in data:
            sev = entry.get('severity', entry.get('severity_rating'))
            assert sev is not None, \
                f"Missing severity for view {entry.get('view_name', '?')}"
            assert str(sev).lower() in ('critical', 'warning'), \
                f"Severity should be 'critical' or 'warning', got '{sev}'"

    def test_corrected_sql_present(self):
        data = self._load()
        for entry in data:
            sql = entry.get('corrected_sql', '')
            assert sql, f"Missing corrected_sql for {entry.get('view_name', '?')}"
            assert 'CREATE' in str(sql).upper() and 'VIEW' in str(sql).upper(), \
                f"corrected_sql should be a CREATE VIEW statement"

    def test_inventory_view_severity_is_critical(self):
        data = self._load()
        inv = None
        for entry in data:
            if 'inventory' in str(entry.get('view_name', '')).lower():
                inv = entry
                break
        assert inv is not None
        sev = str(inv.get('severity', inv.get('severity_rating', ''))).lower()
        assert sev == 'critical', \
            f"Inventory view severity should be 'critical' (affects monetary values), got '{sev}'"

    def test_corrected_inventory_sql_executes(self):
        """Corrected inventory view SQL should execute without error on the original DB."""
        data = self._load()
        inv = None
        for entry in data:
            if 'inventory' in str(entry.get('view_name', '')).lower():
                inv = entry
                break
        assert inv is not None
        sql = str(inv.get('corrected_sql', ''))
        assert 'CREATE' in sql.upper(), "No CREATE statement in corrected_sql"

        orig = sqlite3.connect('/data/warehouse.db')
        test_conn = sqlite3.connect(':memory:')
        orig.backup(test_conn)
        orig.close()

        tc = test_conn.cursor()
        tc.execute("DROP VIEW IF EXISTS v_inventory_value")
        tc.execute("DROP VIEW IF EXISTS v_inventory_value_corrected")
        try:
            tc.execute(sql)
        except Exception as e:
            pytest.fail(f"Corrected inventory SQL failed to execute: {e}")
        finally:
            test_conn.close()
