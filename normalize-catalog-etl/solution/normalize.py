#!/usr/bin/env python3
"""

Multi-source product catalog reconciliation pipeline.
Parses three heterogeneous feeds, applies temporal FX conversion with
correction overrides, deduplicates by REF code, resolves supplier aliases,
normalizes categories, quarantines invalid records, and builds analytics.
"""
import sqlite3
import json
import csv
import re
import os
import sys
from datetime import datetime, timezone


# -- Feed Parsers ----------------------------------------------------------------


def parse_alpha_csv(filepath):
    """Semicolon-delimited CSV with European number/date conventions."""
    products = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            price_str = row['price'].replace('.', '').replace(',', '.')
            price = float(price_str)

            date = datetime.strptime(row['received_date'].strip(), '%d.%m.%Y').strftime('%Y-%m-%d')

            parts = [p.strip().title() for p in row['category'].split('>')]
            category = parts[0] if parts else ''
            subcategory = parts[1] if len(parts) > 1 else ''

            is_active = 1 if row['status'].strip().lower() == 'aktiv' else 0
            tags = [t.strip() for t in row['tags'].split(',') if t.strip()]

            ref_match = re.search(r'REF:P\d+', row['description'])
            ref_code = ref_match.group(0) if ref_match else None

            products.append({
                'sku': row['sku'].strip(),
                'name': row['product_name'].strip(),
                'description': row['description'].strip(),
                'price': price,
                'currency': row['currency'].strip(),
                'category': category,
                'subcategory': subcategory,
                'supplier_name': row['supplier'].strip(),
                'received_date': date,
                'quantity': int(row['quantity'].strip()),
                'is_active': is_active,
                'tags': tags,
                'ref_code': ref_code,
                'source_feed': 'alpha',
            })
    return products


def parse_beta_json(filepath):
    """JSON array with nested price/supplier/category objects, Unix timestamps."""
    products = []
    with open(filepath, 'r') as f:
        data = json.load(f)

    for item in data:
        price = float(item['price']['amount'])
        currency = item['price']['currency']

        date = datetime.fromtimestamp(item['timestamp'], tz=timezone.utc).strftime('%Y-%m-%d')

        parts = [p.strip().title() for p in item['category']['path'].split('/')]
        category = parts[0] if parts else ''
        subcategory = parts[1] if len(parts) > 1 else ''

        is_active = 1 if item['active'] else 0
        tags = list(item['tags'])
        supplier_name = item['supplier']['name'].strip()

        ref_match = re.search(r'REF:P\d+', item['description'])
        ref_code = ref_match.group(0) if ref_match else None

        products.append({
            'sku': item['sku'],
            'name': item['name'].strip(),
            'description': item['description'].strip(),
            'price': price,
            'currency': currency,
            'category': category,
            'subcategory': subcategory,
            'supplier_name': supplier_name,
            'received_date': date,
            'quantity': int(item['quantity']),
            'is_active': is_active,
            'tags': tags,
            'ref_code': ref_code,
            'source_feed': 'beta',
        })
    return products


def parse_gamma_ndjson(filepath):
    """Newline-delimited JSON with pipe-delimited tags, YYYY/MM/DD dates."""
    products = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)

            price_parts = item['price'].split()
            currency = price_parts[0]
            price = float(price_parts[1])

            date = item['date'].replace('/', '-')

            parts = [p.strip().title() for p in item['category'].split('::')]
            category = parts[0] if parts else ''
            subcategory = parts[1] if len(parts) > 1 else ''

            is_active = 1 if item['status'].upper() == 'Y' else 0
            tags = [t.strip() for t in item['tags'].split('|') if t.strip()]

            ref_match = re.search(r'REF:P\d+', item['description'])
            ref_code = ref_match.group(0) if ref_match else None

            products.append({
                'sku': item['sku'],
                'name': item['name'].strip(),
                'description': item['description'].strip(),
                'price': price,
                'currency': currency,
                'category': category,
                'subcategory': subcategory,
                'supplier_name': item['supplier'].strip(),
                'received_date': date,
                'quantity': int(item['quantity']),
                'is_active': is_active,
                'tags': tags,
                'ref_code': ref_code,
                'source_feed': 'gamma',
            })
    return products


# -- Main Pipeline ---------------------------------------------------------------


def main():
    # Load all feeds
    all_products = []
    all_products.extend(parse_alpha_csv('/app/feeds/alpha.csv'))
    all_products.extend(parse_beta_json('/app/feeds/beta.json'))
    all_products.extend(parse_gamma_ndjson('/app/feeds/gamma.ndjson'))

    # Quarantine invalid records
    quarantined = []
    valid_products = []
    for p in all_products:
        if p['price'] <= 0:
            quarantined.append({
                'source_sku': p['sku'],
                'product_name': p['name'],
                'reason': 'non-positive price',
            })
        elif p['quantity'] < 0:
            quarantined.append({
                'source_sku': p['sku'],
                'product_name': p['name'],
                'reason': 'negative quantity',
            })
        else:
            valid_products.append(p)

    # Load reference data
    ref_db = sqlite3.connect('/app/reference.db')
    ref_db.row_factory = sqlite3.Row

    # Verify reference DB tables exist
    ref_tables = [r[0] for r in ref_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for required_table in ['fx_history', 'fx_corrections', 'supplier_directory', 'supplier_aliases']:
        if required_table not in ref_tables:
            print(f"ERROR: reference.db missing table '{required_table}'. Found: {ref_tables}", file=sys.stderr)
            sys.exit(1)

    # Load FX corrections (override fx_history for matching currency/date range)
    fx_corrections = []
    for row in ref_db.execute(
        "SELECT currency, date_from, date_to, corrected_rate FROM fx_corrections"
    ).fetchall():
        fx_corrections.append(
            (row['currency'], row['date_from'], row['date_to'], row['corrected_rate'])
        )

    # Temporal FX rates (sorted desc by effective_from per currency)
    fx_rates = {}
    for row in ref_db.execute(
        "SELECT currency, rate_to_usd, effective_from "
        "FROM fx_history ORDER BY effective_from DESC"
    ).fetchall():
        fx_rates.setdefault(row['currency'], []).append(
            (row['effective_from'], row['rate_to_usd'])
        )

    def get_fx_rate(currency, date_str):
        if currency == 'USD':
            return 1.0
        # Check corrections first: use corrected rate if currency and date match
        for corr_currency, date_from, date_to, corrected_rate in fx_corrections:
            if corr_currency == currency and date_from <= date_str <= date_to:
                return corrected_rate
        # Fall back to fx_history: most recent rate effective on or before date
        rates = fx_rates.get(currency, [])
        for effective_from, rate in rates:
            if effective_from <= date_str:
                return rate
        return rates[-1][1] if rates else 1.0

    # Compute FX rates and converted prices for all valid products
    for p in valid_products:
        rate = get_fx_rate(p['currency'], p['received_date'])
        p['fx_rate'] = rate
        p['price_usd'] = round(p['price'] * rate, 2)

    # Supplier directory + aliases
    suppliers = {}
    for row in ref_db.execute("SELECT * FROM supplier_directory").fetchall():
        suppliers[row['id']] = dict(row)

    alias_map = {}
    for row in ref_db.execute("SELECT * FROM supplier_aliases").fetchall():
        alias_map[row['alias'].lower()] = row['directory_id']
    for sid, s in suppliers.items():
        alias_map[s['canonical_name'].lower()] = sid

    ref_db.close()

    def resolve_supplier(name):
        return alias_map.get(name.lower())

    # Deduplicate by REF code (most recent date wins, tags merged)
    ref_groups = {}
    no_ref = []
    for p in valid_products:
        if p['ref_code']:
            ref_groups.setdefault(p['ref_code'], []).append(p)
        else:
            no_ref.append(p)

    deduped = []
    for ref_code, group in ref_groups.items():
        group.sort(key=lambda x: x['received_date'], reverse=True)
        winner = group[0].copy()
        all_tags = set()
        for p in group:
            all_tags.update(p['tags'])
        winner['tags'] = sorted(all_tags)
        deduped.append(winner)
    deduped.extend(no_ref)

    # Track winner SKUs for price_history
    winner_skus = {p['sku'] for p in deduped}

    # Create catalog database
    if os.path.exists('/app/catalog.db'):
        os.remove('/app/catalog.db')
    db = sqlite3.connect('/app/catalog.db')
    db.execute("PRAGMA foreign_keys = ON")

    # Suppliers table (from reference data for used suppliers)
    db.execute('''CREATE TABLE suppliers (
        id INTEGER PRIMARY KEY,
        canonical_name TEXT NOT NULL UNIQUE,
        country TEXT,
        rating REAL
    )''')
    used_sids = set()
    for p in deduped:
        sid = resolve_supplier(p['supplier_name'])
        if sid:
            used_sids.add(sid)
    sup_id_map = {}
    for i, sid in enumerate(sorted(used_sids), 1):
        s = suppliers[sid]
        db.execute(
            "INSERT INTO suppliers (id, canonical_name, country, rating) VALUES (?,?,?,?)",
            (i, s['canonical_name'], s['country'], s['rating'])
        )
        sup_id_map[sid] = i

    # Categories table
    cat_pairs = set()
    for p in deduped:
        cat_pairs.add((p['category'], p['subcategory']))
    db.execute('''CREATE TABLE categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        subcategory TEXT NOT NULL,
        UNIQUE(name, subcategory)
    )''')
    cat_id_map = {}
    for i, (cat, subcat) in enumerate(sorted(cat_pairs), 1):
        db.execute("INSERT INTO categories (id, name, subcategory) VALUES (?,?,?)",
                   (i, cat, subcat))
        cat_id_map[(cat, subcat)] = i

    # Products table
    db.execute('''CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        product_name TEXT NOT NULL,
        description TEXT,
        price_usd REAL NOT NULL,
        category_id INTEGER REFERENCES categories(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        received_date TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        is_active INTEGER NOT NULL,
        source_sku TEXT NOT NULL
    )''')

    # Product tags table
    db.execute('''CREATE TABLE product_tags (
        product_id INTEGER REFERENCES products(id),
        tag TEXT NOT NULL
    )''')

    # Quarantined records table
    db.execute('''CREATE TABLE quarantined_records (
        source_sku TEXT,
        product_name TEXT,
        reason TEXT
    )''')
    for q in quarantined:
        db.execute("INSERT INTO quarantined_records VALUES (?,?,?)",
                   (q['source_sku'], q['product_name'], q['reason']))

    # Insert products and tags
    for p in deduped:
        sid = resolve_supplier(p['supplier_name'])
        supplier_db_id = sup_id_map.get(sid) if sid else None
        cid = cat_id_map.get((p['category'], p['subcategory']))

        cur = db.execute(
            """INSERT INTO products
               (product_name, description, price_usd, category_id,
                supplier_id, received_date, quantity, is_active, source_sku)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (p['name'], p['description'], p['price_usd'], cid, supplier_db_id,
             p['received_date'], p['quantity'], p['is_active'], p['sku'])
        )
        pid = cur.lastrowid
        for tag in p['tags']:
            db.execute("INSERT INTO product_tags (product_id, tag) VALUES (?,?)",
                       (pid, tag))

    # Price history table -- audit trail of ALL valid observations
    db.execute('''CREATE TABLE price_history (
        id INTEGER PRIMARY KEY,
        source_sku TEXT NOT NULL,
        product_name TEXT NOT NULL,
        original_price REAL NOT NULL,
        original_currency TEXT NOT NULL,
        fx_rate_applied REAL NOT NULL,
        price_usd REAL NOT NULL,
        source_feed TEXT NOT NULL,
        received_date TEXT NOT NULL,
        is_catalog_entry INTEGER NOT NULL
    )''')
    for p in valid_products:
        is_catalog = 1 if p['sku'] in winner_skus else 0
        db.execute(
            """INSERT INTO price_history
               (source_sku, product_name, original_price, original_currency,
                fx_rate_applied, price_usd, source_feed, received_date,
                is_catalog_entry)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (p['sku'], p['name'], p['price'], p['currency'],
             p['fx_rate'], p['price_usd'], p['source_feed'],
             p['received_date'], is_catalog)
        )

    # Category analytics -- materialized aggregations from final catalog
    db.execute('''CREATE TABLE category_analytics (
        category TEXT NOT NULL,
        subcategory TEXT NOT NULL,
        product_count INTEGER NOT NULL,
        avg_price_usd REAL NOT NULL,
        min_price_usd REAL NOT NULL,
        max_price_usd REAL NOT NULL,
        total_quantity INTEGER NOT NULL,
        distinct_supplier_count INTEGER NOT NULL,
        PRIMARY KEY(category, subcategory)
    )''')
    db.execute('''INSERT INTO category_analytics
        SELECT c.name, c.subcategory,
            count(*) as product_count,
            round(avg(p.price_usd), 2) as avg_price_usd,
            min(p.price_usd) as min_price_usd,
            max(p.price_usd) as max_price_usd,
            sum(p.quantity) as total_quantity,
            count(distinct p.supplier_id) as distinct_supplier_count
        FROM products p
        JOIN categories c ON p.category_id = c.id
        GROUP BY c.name, c.subcategory
    ''')

    db.commit()
    db.close()
    print("Normalization complete.")


if __name__ == '__main__':
    main()
