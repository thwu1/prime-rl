#!/usr/bin/env python3
"""Generate warehouse.db with embedded data integrity issues and supplementary files."""
import csv
import sqlite3


def main():
    conn = sqlite3.connect('/data/warehouse.db')
    c = conn.cursor()

    # Tables use flexible typing (no STRICT) — columns without declared types
    # get BLOB affinity, storing values in their original type without conversion.
    c.executescript('''
        CREATE TABLE parts (
            id INTEGER PRIMARY KEY,
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            unit_cost,
            category TEXT,
            specs TEXT
        );

        CREATE TABLE bom_edges (
            parent_id,
            child_id,
            quantity,
            PRIMARY KEY (parent_id, child_id)
        );

        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_id,
            warehouse TEXT NOT NULL,
            qty_on_hand INTEGER NOT NULL,
            last_audit TEXT
        );

        CREATE TABLE purchase_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_id INTEGER,
            supplier TEXT,
            unit_price REAL,
            quantity INTEGER,
            order_date TEXT
        );

        CREATE TABLE schema_docs (
            table_name TEXT,
            column_name TEXT,
            intended_type TEXT,
            description TEXT
        );

        CREATE TABLE business_rules (
            rule_id INTEGER PRIMARY KEY,
            domain TEXT,
            rule_text TEXT
        );
    ''')

    # Document intended types
    docs = [
        ('parts', 'unit_cost', 'REAL',
         'Cost per unit in USD. Must be a non-negative real number.'),
        ('bom_edges', 'parent_id', 'INTEGER',
         'References parts.id. Foreign key to parent assembly or subassembly.'),
        ('bom_edges', 'child_id', 'INTEGER',
         'References parts.id. Foreign key to child component.'),
        ('bom_edges', 'quantity', 'INTEGER',
         'Number of child units required per parent. Positive integer.'),
        ('inventory', 'part_id', 'INTEGER',
         'References parts.id. Foreign key to stocked part.'),
        ('inventory', 'last_audit', 'TEXT (ISO-8601)',
         'Date of last physical count. Should be in YYYY-MM-DD format.'),
    ]
    c.executemany('INSERT INTO schema_docs VALUES (?,?,?,?)', docs)

    # Business rules
    rules = [
        (1, 'costing',
         'BOM cost for an assembly is computed recursively: own unit_cost plus '
         'SUM(quantity * child_total_cost) for all children.'),
        (2, 'costing',
         'For parts with indeterminate unit costs, use the active contracted '
         'rate from the supplier rate card (/data/supplier_rates.csv).'),
        (3, 'valuation',
         'Inventory value per warehouse is SUM(qty_on_hand * resolved_unit_cost) '
         'across all inventory records for that location.'),
        (4, 'data_quality',
         'All data quality findings should be documented in the audit report.'),
    ]
    c.executemany('INSERT INTO business_rules VALUES (?,?,?)', rules)

    # ---- Parts (15 total) ----
    correct_parts = [
        (1, 'ASM-A', 'Alpha Assembly', 0.0, 'assembly',
         '{"desc":"Main product alpha","weight_kg":2.5}'),
        (2, 'ASM-B', 'Beta Assembly', 0.0, 'assembly',
         '{"desc":"Main product beta","weight_kg":1.8}'),
        (3, 'SUB-P', 'Power Unit', 1.50, 'sub',
         '{"voltage":12,"current_a":5}'),
        (4, 'SUB-Q', 'Sensor Unit', 2.00, 'sub',
         '{channels: 4, "resolution":"12-bit"}'),          # MALFORMED JSON
        (5, 'SUB-R', 'Frame Unit', 1.00, 'sub',
         '{"material":"aluminum","finish":"anodized"}'),
        (7, 'RAW-02', 'Copper Coil', 6.50, 'raw',
         '{"gauge":18}'),
        (9, 'RAW-04', 'Resistor Pack', 0.50, 'raw',
         '{"count":100,"tolerance":"5%"}'),
        (11, 'RAW-06', 'Bearing', 2.80, 'raw',
         '{"bore_mm":8,"type":"ball"}'),
        (12, 'RAW-07', 'Bolt Pack', 0.40, 'raw',
         '{"size":"M4x10","count":50}'),
        (13, 'RAW-08', 'Capacitor', 0.25, 'raw',
         '{"capacitance_uf":100,"voltage":25}'),
        (15, 'RAW-10', 'LED Module', 1.80, 'raw',
         '{"wavelength":630,"color":"red"'),                # MALFORMED JSON
    ]
    c.executemany('INSERT INTO parts VALUES (?,?,?,?,?,?)', correct_parts)

    # Parts with TEXT unit_cost — type violations
    c.execute("INSERT INTO parts VALUES (6, 'RAW-01', 'Steel Sheet', '$4.00', 'raw', "
              "'{\"thickness_mm\":4,\"grade\":\"304\"}')")
    c.execute("INSERT INTO parts VALUES (8, 'RAW-03', 'PCB Board', '$11.00', 'raw', "
              "'{\"layers\":4,\"size_mm\":\"100x80\"}')")
    c.execute("INSERT INTO parts VALUES (10, 'RAW-05', 'IC Chip', '7.25', 'raw', "
              "'{\"package\":\"TQFP-44\",\"freq_mhz\":16}')")
    c.execute("INSERT INTO parts VALUES (14, 'RAW-09', 'Transformer', 'TBD', 'raw', "
              "'{\"power_w\":60,\"input_v\":220}')")

    # ---- BOM Edges ----
    correct_edges = [
        (1, 3, 1),     # ASM-A -> Power Unit x1
        (1, 4, 2),     # ASM-A -> Sensor Unit x2
        (1, 5, 1),     # ASM-A -> Frame Unit x1
        (2, 3, 1),     # ASM-B -> Power Unit x1
        (2, 5, 2),     # ASM-B -> Frame Unit x2
        (3, 7, 1),     # SUB-P -> Copper Coil x1
        (3, 14, 1),    # SUB-P -> Transformer x1
        (3, 13, 4),    # SUB-P -> Capacitor x4
        (3, 12, 6),    # SUB-P -> Bolt Pack x6
        (4, 8, 1),     # SUB-Q -> PCB Board x1
        (4, 10, 2),    # SUB-Q -> IC Chip x2
        (4, 9, 10),    # SUB-Q -> Resistor Pack x10
        (4, 15, 3),    # SUB-Q -> LED Module x3
        (5, 6, 3),     # SUB-R -> Steel Sheet x3
        (5, 12, 8),    # SUB-R -> Bolt Pack x8
        (5, 11, 2),    # SUB-R -> Bearing x2
        (15, 4, 1),    # CYCLE: LED Module -> Sensor Unit
        (11, 5, 1),    # CYCLE: Bearing -> Frame Unit
    ]
    c.executemany('INSERT INTO bom_edges VALUES (?,?,?)', correct_edges)

    # BOM edge with TEXT parent_id — type violation causing silent JOIN failure
    c.execute("INSERT INTO bom_edges VALUES ('2', 6, 3)")   # ASM-B -> Steel Sheet x3

    # ---- Inventory ----
    correct_inventory = [
        (6, 'EAST', 500, '2024-03-15'),
        (6, 'WEST', 300, '03/20/2024'),         # DATE ANOMALY: MM/DD/YYYY
        (7, 'EAST', 200, '2024-03-15'),
        (8, 'EAST', 150, '1710460800'),          # DATE ANOMALY: epoch timestamp
        (8, 'WEST', 75, '2024-03-18'),
        (9, 'EAST', 5000, '2024-03-15'),
        (10, 'EAST', 400, '2024-03-15'),
        (11, 'EAST', 800, '2024-03-15'),
        (12, 'EAST', 10000, '2024-03-15'),
        (12, 'WEST', 5000, '03/16/2024'),        # DATE ANOMALY: MM/DD/YYYY
        (13, 'EAST', 8000, '2024-03-15'),
        (14, 'EAST', 100, '2024-03-15'),
        (14, 'WEST', 50, '2024-03-18'),
        (15, 'EAST', 600, '2024-03-15'),
    ]
    c.executemany(
        'INSERT INTO inventory (part_id, warehouse, qty_on_hand, last_audit) VALUES (?,?,?,?)',
        correct_inventory)

    # Inventory with TEXT part_id — type violation
    c.execute("INSERT INTO inventory (part_id, warehouse, qty_on_hand, last_audit) "
              "VALUES ('10', 'WEST', 250, '2024-03-17')")

    # ---- Purchase History (deliberately NO entries for part 14/Transformer) ----
    purchases = [
        (7, 'MetalCo', 6.30, 500, '2024-01-10'),
        (7, 'MetalCo', 6.50, 300, '2024-04-15'),
        (6, 'SteelWorks', 3.80, 1000, '2023-09-01'),
        (6, 'SteelWorks', 4.00, 800, '2024-02-28'),
        (8, 'BoardHouse', 10.50, 500, '2023-10-15'),
        (8, 'BoardHouse', 11.00, 400, '2024-03-10'),
        (10, 'ChipFab', 7.00, 1000, '2023-12-01'),
        (10, 'ChipFab', 7.25, 800, '2024-05-15'),
        (9, 'ElecParts', 0.48, 10000, '2024-01-20'),
        (11, 'BearingCo', 2.80, 2000, '2024-02-10'),
        (13, 'ElecParts', 0.25, 5000, '2024-03-01'),
        (15, 'LEDWorld', 1.80, 3000, '2024-04-05'),
        (12, 'HardwareCo', 0.40, 20000, '2024-01-15'),
    ]
    c.executemany(
        'INSERT INTO purchase_history (part_id, supplier, unit_price, quantity, order_date) '
        'VALUES (?,?,?,?,?)', purchases)

    # ---- Views (broken by type mismatches in source data — agent must diagnose) ----
    c.execute('''
        CREATE VIEW v_bom_summary AS
        SELECT p.sku AS parent_sku, c.sku AS child_sku, be.quantity
        FROM parts p
        JOIN bom_edges be ON p.id = be.parent_id
        JOIN parts c ON be.child_id = c.id
    ''')

    c.execute('''
        CREATE VIEW v_inventory_value AS
        SELECT i.id, p.sku, i.warehouse, i.qty_on_hand, p.unit_cost,
               i.qty_on_hand * p.unit_cost AS line_value
        FROM inventory i
        JOIN parts p ON i.part_id = p.id
    ''')

    conn.commit()
    conn.close()

    # ---- Supplier Rate Card (external CSV) ----
    with open('/data/supplier_rates.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['sku', 'supplier', 'contracted_rate', 'effective_date', 'active'])
        rates = [
            ('RAW-01', 'SteelWorks', '4.00', '2024-02-28', 'true'),
            ('RAW-01', 'MetalSupply', '4.25', '2024-01-15', 'false'),
            ('RAW-02', 'MetalCo', '6.50', '2024-04-15', 'true'),
            ('RAW-03', 'BoardHouse', '11.00', '2024-03-10', 'true'),
            ('RAW-03', 'CircuitDirect', '10.75', '2024-02-01', 'false'),
            ('RAW-04', 'ElecParts', '0.50', '2024-01-20', 'true'),
            ('RAW-05', 'ChipFab', '7.25', '2024-05-15', 'true'),
            ('RAW-06', 'BearingCo', '2.80', '2024-02-10', 'true'),
            ('RAW-07', 'HardwareCo', '0.40', '2024-01-15', 'true'),
            ('RAW-08', 'ElecParts', '0.25', '2024-03-01', 'true'),
            ('RAW-09', 'PowerParts', '9.00', '2024-06-20', 'true'),
            ('RAW-09', 'ElectroCorp', '8.75', '2023-11-15', 'false'),
            ('RAW-10', 'LEDWorld', '1.80', '2024-04-05', 'true'),
        ]
        w.writerows(rates)


if __name__ == '__main__':
    main()
