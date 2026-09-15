
import sqlite3
import json
import os
import pytest

REPAIRED_DB = '/app/analytics_repaired.db'
EXPECTED_FILE = '/app/expected.json'
REPAIR_REPORT_FILE = '/app/repair_report.json'


@pytest.fixture(scope='module')
def expected():
    with open(EXPECTED_FILE) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def conn():
    c = sqlite3.connect(REPAIRED_DB)
    yield c
    c.close()


# ═══════════════════════════════════════════════════════════
# File existence and integrity
# ═══════════════════════════════════════════════════════════

def test_repaired_db_exists():
    assert os.path.exists(REPAIRED_DB), 'Repaired database not found'


def test_original_not_modified():
    """Original database must not be modified."""
    original = sqlite3.connect('/app/analytics.db')
    cnt = original.execute(
        "SELECT COUNT(*) FROM order_lines "
        "WHERE typeof(unit_price) NOT IN ('real','integer')"
    ).fetchone()[0]
    original.close()
    assert cnt > 0, 'Original database appears to have been modified'


def test_integrity_check(conn):
    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    assert result == 'ok', f'integrity_check failed: {result}'


def test_foreign_key_check(conn):
    conn.execute('PRAGMA foreign_keys = ON')
    violations = conn.execute('PRAGMA foreign_key_check').fetchall()
    assert len(violations) == 0, \
        f'{len(violations)} FK violations: {violations[:5]}'


# ═══════════════════════════════════════════════════════════
# Query result verification
# ═══════════════════════════════════════════════════════════

def test_q1_revenue_by_category(conn, expected):
    rows = conn.execute("""
        SELECT p.category,
               ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue,
               SUM(ol.quantity) as total_units
        FROM order_lines ol
        JOIN orders o ON ol.order_id = o.order_id
        JOIN products p ON ol.product_id = p.product_id
        WHERE o.status = 'completed'
        GROUP BY p.category ORDER BY p.category
    """).fetchall()
    exp = expected['Q1']
    assert len(rows) == len(exp), \
        f'Q1: expected {len(exp)} rows, got {len(rows)}'
    for actual, exp_row in zip(rows, exp):
        assert actual[0] == exp_row['category'], \
            f"Q1 category mismatch: {actual[0]} != {exp_row['category']}"
        assert abs(actual[1] - exp_row['revenue']) < 0.02, \
            f"Q1 {actual[0]}: revenue {actual[1]} != {exp_row['revenue']}"
        assert actual[2] == exp_row['total_units'], \
            f"Q1 {actual[0]}: units {actual[2]} != {exp_row['total_units']}"


def test_q2_revenue_by_tier(conn, expected):
    rows = conn.execute("""
        SELECT c.tier,
               COUNT(DISTINCT o.order_id) as order_count,
               ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_lines ol ON o.order_id = ol.order_id
        WHERE o.status = 'completed'
        GROUP BY c.tier ORDER BY c.tier
    """).fetchall()
    exp = expected['Q2']
    assert len(rows) == len(exp)
    for actual, exp_row in zip(rows, exp):
        assert actual[0] == exp_row['tier']
        assert actual[1] == exp_row['order_count'], \
            f"Q2 {actual[0]}: orders {actual[1]} != {exp_row['order_count']}"
        assert abs(actual[2] - exp_row['revenue']) < 0.02, \
            f"Q2 {actual[0]}: revenue {actual[2]} != {exp_row['revenue']}"


def test_q3_inventory_balance(conn, expected):
    rows = conn.execute("""
        SELECT p.sku, p.name, SUM(il.quantity_change) as balance
        FROM products p
        JOIN inventory_log il ON p.product_id = il.product_id
        GROUP BY p.product_id ORDER BY p.sku
    """).fetchall()
    exp = expected['Q3']
    assert len(rows) == len(exp)
    for actual, exp_row in zip(rows, exp):
        assert actual[0] == exp_row['sku']
        assert actual[2] == exp_row['balance'], \
            f"Q3 {actual[0]}: balance {actual[2]} != {exp_row['balance']}"


def test_q4_product_demand(conn, expected):
    rows = conn.execute("""
        SELECT p.category,
               COUNT(*) as line_count,
               SUM(ol.quantity) as total_quantity,
               ROUND(SUM(ol.unit_price * ol.quantity), 2) as gross_demand
        FROM order_lines ol
        JOIN products p ON ol.product_id = p.product_id
        GROUP BY p.category ORDER BY p.category
    """).fetchall()
    exp = expected['Q4']
    assert len(rows) == len(exp)
    for actual, exp_row in zip(rows, exp):
        assert actual[0] == exp_row['category']
        assert actual[1] == exp_row['line_count'], \
            f"Q4 {actual[0]}: lines {actual[1]} != {exp_row['line_count']}"
        assert actual[2] == exp_row['total_quantity'], \
            f"Q4 {actual[0]}: qty {actual[2]} != {exp_row['total_quantity']}"
        assert abs(actual[3] - exp_row['gross_demand']) < 0.02, \
            f"Q4 {actual[0]}: demand {actual[3]} != {exp_row['gross_demand']}"


def test_q5_daily_revenue_summary(conn, expected):
    rows = conn.execute("""
        SELECT strftime('%Y-%m', rev_date) as month,
               ROUND(SUM(revenue), 2) as total_revenue,
               SUM(units_sold) as total_units
        FROM daily_revenue
        GROUP BY strftime('%Y-%m', rev_date)
        ORDER BY month
    """).fetchall()
    exp = expected['Q5']
    assert len(rows) == len(exp)
    for actual, exp_row in zip(rows, exp):
        assert actual[0] == exp_row['month']
        assert abs(actual[1] - exp_row['total_revenue']) < 0.02, \
            f"Q5 {actual[0]}: revenue {actual[1]} != {exp_row['total_revenue']}"
        assert actual[2] == exp_row['total_units'], \
            f"Q5 {actual[0]}: units {actual[2]} != {exp_row['total_units']}"


# ═══════════════════════════════════════════════════════════
# Structural integrity checks
# ═══════════════════════════════════════════════════════════

def test_no_text_unit_prices(conn):
    count = conn.execute(
        "SELECT COUNT(*) FROM order_lines "
        "WHERE typeof(unit_price) NOT IN ('real','integer')"
    ).fetchone()[0]
    assert count == 0, f'{count} order_lines have non-numeric unit_price'


def test_no_excessive_discounts(conn):
    count = conn.execute(
        'SELECT COUNT(*) FROM order_lines WHERE discount_pct > 1.0'
    ).fetchone()[0]
    assert count == 0, f'{count} order_lines have discount_pct > 1.0'


def test_no_orphaned_order_lines(conn):
    count = conn.execute(
        "SELECT COUNT(*) FROM order_lines "
        "WHERE order_id NOT IN (SELECT order_id FROM orders)"
    ).fetchone()[0]
    assert count == 0, f'{count} orphaned order_lines found'


def test_inventory_sign_convention(conn):
    bad_in = conn.execute(
        "SELECT COUNT(*) FROM inventory_log "
        "WHERE change_type='in' AND quantity_change < 0"
    ).fetchone()[0]
    bad_out = conn.execute(
        "SELECT COUNT(*) FROM inventory_log "
        "WHERE change_type='out' AND quantity_change > 0"
    ).fetchone()[0]
    assert bad_in == 0, f"{bad_in} 'in' entries have negative quantity"
    assert bad_out == 0, f"{bad_out} 'out' entries have positive quantity"


def test_no_null_category_daily_revenue(conn):
    count = conn.execute(
        'SELECT COUNT(*) FROM daily_revenue WHERE category IS NULL'
    ).fetchone()[0]
    assert count == 0, f'{count} daily_revenue rows have NULL category'


def test_record_counts(conn, expected):
    ol = conn.execute('SELECT COUNT(*) FROM order_lines').fetchone()[0]
    assert ol == expected['counts']['order_lines'], \
        f"order_lines: {ol} != {expected['counts']['order_lines']}"

    dr = conn.execute('SELECT COUNT(*) FROM daily_revenue').fetchone()[0]
    assert dr == expected['counts']['daily_revenue'], \
        f"daily_revenue: {dr} != {expected['counts']['daily_revenue']}"

    il = conn.execute('SELECT COUNT(*) FROM inventory_log').fetchone()[0]
    assert il == expected['counts']['inventory_log'], \
        f"inventory_log: {il} != {expected['counts']['inventory_log']}"


def test_schema_preserved(conn):
    tables = set(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall())
    required = {'customers', 'products', 'orders', 'order_lines',
                'inventory_log', 'daily_revenue'}
    missing = required - tables
    assert not missing, f'Missing tables: {missing}'


# ═══════════════════════════════════════════════════════════
# Preventive triggers
# ═══════════════════════════════════════════════════════════

def test_preventive_triggers_exist(conn):
    """At least 3 preventive triggers must exist in the repaired database."""
    triggers = conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    assert len(triggers) >= 3, \
        f'Expected at least 3 preventive triggers, found {len(triggers)}: ' \
        f'{[t[0] for t in triggers]}'


def test_triggers_cover_multiple_tables(conn):
    """Triggers must cover at least 2 different tables."""
    tables = set(r[0] for r in conn.execute(
        "SELECT DISTINCT tbl_name FROM sqlite_master WHERE type='trigger'"
    ).fetchall())
    assert len(tables) >= 2, \
        f'Triggers should cover at least 2 tables, found: {tables}'


def test_trigger_enforces_unit_price_type(conn):
    """A trigger should reject TEXT unit_price values on order_lines."""
    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute(
            "INSERT INTO order_lines VALUES (999999, 1, 1, 1, '$100.00', 0.0)"
        )
        conn.rollback()
        pytest.fail('Trigger should have rejected TEXT unit_price')
    except sqlite3.IntegrityError:
        conn.rollback()
    except sqlite3.OperationalError:
        conn.rollback()


def test_trigger_enforces_discount_range(conn):
    """A trigger should reject discount_pct > 1.0 on order_lines."""
    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute(
            "INSERT INTO order_lines VALUES (999998, 1, 1, 1, 50.0, 15.0)"
        )
        conn.rollback()
        pytest.fail('Trigger should have rejected discount_pct > 1.0')
    except sqlite3.IntegrityError:
        conn.rollback()
    except sqlite3.OperationalError:
        conn.rollback()


def test_trigger_enforces_inventory_sign(conn):
    """A trigger should reject wrong-sign inventory_log entries."""
    try:
        conn.execute(
            "INSERT INTO inventory_log VALUES (999997, 1, 'in', -50, "
            "'2024-01-01', 'TEST')"
        )
        conn.rollback()
        pytest.fail("Trigger should have rejected negative 'in' quantity")
    except sqlite3.IntegrityError:
        conn.rollback()
    except sqlite3.OperationalError:
        conn.rollback()


# ═══════════════════════════════════════════════════════════
# Repair report structure and quality
# ═══════════════════════════════════════════════════════════

def test_repair_report_exists():
    assert os.path.exists(REPAIR_REPORT_FILE), 'repair_report.json not found'


def test_repair_report_phases_structure():
    with open(REPAIR_REPORT_FILE) as f:
        report = json.load(f)

    assert 'phases' in report, "repair_report missing 'phases'"
    phases = report['phases']
    assert isinstance(phases, list)
    assert len(phases) >= 4, \
        f'Expected at least 4 repair phases, found {len(phases)}'

    phase_ids = set()
    for phase in phases:
        assert 'phase_id' in phase, 'Each phase must have a phase_id'
        assert 'depends_on' in phase, 'Each phase must have depends_on'
        assert 'issue' in phase, 'Each phase must have an issue'
        assert 'description' in phase, 'Each phase must have a description'
        assert 'evidence' in phase, 'Each phase must have evidence'
        assert 'approach' in phase, 'Each phase must have an approach'
        assert 'alternatives_considered' in phase, \
            'Each phase must have alternatives_considered'
        assert 'rows_affected' in phase, \
            'Each phase must have rows_affected'
        assert 'sqlite_mechanism' in phase, \
            'Each phase must have sqlite_mechanism'

        assert isinstance(phase['phase_id'], int), \
            'phase_id must be an integer'
        assert isinstance(phase['depends_on'], list), \
            'depends_on must be a list'
        assert isinstance(phase['rows_affected'], int), \
            'rows_affected must be an integer'
        assert phase['rows_affected'] > 0, \
            f"rows_affected must be positive, got {phase['rows_affected']}"
        assert len(phase['description']) >= 20, \
            'description must be substantive (>= 20 chars)'
        assert len(phase['evidence']) >= 20, \
            'evidence must be substantive (>= 20 chars)'
        assert len(phase['approach']) >= 10, \
            'approach must be substantive (>= 10 chars)'
        assert len(phase['alternatives_considered']) >= 10, \
            'alternatives_considered must be substantive (>= 10 chars)'
        assert len(phase['sqlite_mechanism']) >= 10, \
            'sqlite_mechanism must be substantive (>= 10 chars)'

        phase_ids.add(phase['phase_id'])

    # Validate dependency references
    for phase in phases:
        for dep in phase['depends_on']:
            assert dep in phase_ids, \
                f"Phase {phase['phase_id']} depends on unknown phase {dep}"
            assert dep != phase['phase_id'], \
                f"Phase {phase['phase_id']} depends on itself"

    # At least one phase must have dependencies (demonstrating ordering)
    has_deps = any(len(p['depends_on']) > 0 for p in phases)
    assert has_deps, \
        'At least one phase must have dependencies to demonstrate repair ordering'


def test_repair_report_preventive_measures():
    with open(REPAIR_REPORT_FILE) as f:
        report = json.load(f)

    assert 'preventive_measures' in report, \
        "repair_report missing 'preventive_measures'"
    measures = report['preventive_measures']
    assert isinstance(measures, list)
    assert len(measures) >= 3, \
        f'Expected at least 3 preventive measures, found {len(measures)}'

    for m in measures:
        assert 'type' in m, 'Each measure must have a type'
        assert 'name' in m, 'Each measure must have a name'
        assert 'target_table' in m, 'Each measure must have a target_table'
        assert 'definition' in m, 'Each measure must have a definition'
        assert 'rationale' in m, 'Each measure must have a rationale'
        assert m['type'] == 'trigger', \
            f"Measure type must be 'trigger', got '{m['type']}'"
        assert 'CREATE TRIGGER' in m['definition'].upper(), \
            'definition must contain a CREATE TRIGGER statement'
