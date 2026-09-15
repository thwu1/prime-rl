#!/usr/bin/env python3
"""Create the catalog SQLite database for the multi-operator query optimizer."""
import sqlite3
import os

DB_PATH = '/data/catalog.db'

def create():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE tables (
        table_name TEXT PRIMARY KEY,
        row_count INTEGER,
        page_count INTEGER,
        clustered_on TEXT
    )''')
    tables_data = [
        ('orders', 10000000, 25000, 'date_id'),
        ('customers', 500000, 2500, 'customer_id'),
        ('products', 100000, 500, 'product_id'),
        ('stores', 5000, 25, None),
        ('dates', 3650, 18, 'date_id'),
    ]
    c.executemany('INSERT INTO tables VALUES (?,?,?,?)', tables_data)

    c.execute('''CREATE TABLE columns (
        table_name TEXT,
        column_name TEXT,
        distinct_values INTEGER,
        PRIMARY KEY (table_name, column_name)
    )''')
    columns_data = [
        ('orders', 'order_id', 10000000),
        ('orders', 'customer_id', 500000),
        ('orders', 'product_id', 100000),
        ('orders', 'store_id', 5000),
        ('orders', 'date_id', 3650),
        ('orders', 'amount', 1000000),
        ('orders', 'quantity', 100),
        ('orders', 'discount', 20),
        ('customers', 'customer_id', 500000),
        ('customers', 'name', 490000),
        ('customers', 'region', 5),
        ('customers', 'segment', 4),
        ('customers', 'credit_limit', 10000),
        ('products', 'product_id', 100000),
        ('products', 'name', 99000),
        ('products', 'category', 50),
        ('products', 'brand', 500),
        ('products', 'price', 5000),
        ('stores', 'store_id', 5000),
        ('stores', 'name', 4900),
        ('stores', 'city', 2000),
        ('stores', 'state', 50),
        ('dates', 'date_id', 3650),
        ('dates', 'year', 10),
        ('dates', 'month', 12),
        ('dates', 'quarter', 4),
    ]
    c.executemany('INSERT INTO columns VALUES (?,?,?)', columns_data)

    c.execute('''CREATE TABLE indexes (
        index_name TEXT PRIMARY KEY,
        table_name TEXT,
        column_name TEXT,
        index_pages INTEGER
    )''')
    indexes_data = [
        ('idx_customers_region', 'customers', 'region', 50),
        ('idx_products_category', 'products', 'category', 100),
        ('idx_dates_year', 'dates', 'year', 10),
        ('idx_stores_state', 'stores', 'state', 5),
    ]
    c.executemany('INSERT INTO indexes VALUES (?,?,?,?)', indexes_data)

    c.execute('''CREATE TABLE join_selectivity (
        left_col TEXT,
        right_col TEXT,
        distinct_values INTEGER
    )''')
    join_data = [
        ('orders.customer_id', 'customers.customer_id', 500000),
        ('orders.product_id', 'products.product_id', 100000),
        ('orders.store_id', 'stores.store_id', 5000),
        ('orders.date_id', 'dates.date_id', 3650),
    ]
    c.executemany('INSERT INTO join_selectivity VALUES (?,?,?)', join_data)

    c.execute('''CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value REAL
    )''')
    config_data = [
        ('seq_page_cost', 1.0),
        ('random_page_cost', 4.0),
        ('cpu_tuple_cost', 0.01),
        ('cpu_index_cost', 0.005),
        ('cpu_operator_cost', 0.0025),
        ('hash_build_factor', 4.0),
        ('hash_probe_factor', 1.5),
        ('sort_cpu_factor', 2.0),
        ('merge_cpu_factor', 1.0),
        ('index_selectivity_threshold', 0.15),
    ]
    c.executemany('INSERT INTO config VALUES (?,?)', config_data)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    create()
    print(f"Created {DB_PATH}")
