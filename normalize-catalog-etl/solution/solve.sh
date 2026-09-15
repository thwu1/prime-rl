#!/bin/bash

pip3 install sqlite-utils==3.38 -q

# Step 1: Run the ETL pipeline
python3 /solution/normalize.py
if [ $? -ne 0 ]; then
    echo "ERROR: normalize.py failed"
    exit 1
fi

# Step 2: Enable FTS5 with porter tokenizer
sqlite-utils enable-fts /app/catalog.db products product_name description \
    --fts5 --tokenize porter

# Step 3: Create the product_summary view
sqlite-utils create-view /app/catalog.db product_summary \
    "SELECT p.id, p.product_name, p.price_usd, c.name AS category, c.subcategory, s.canonical_name AS supplier_name, s.country AS supplier_country, p.received_date, p.quantity, p.is_active, p.source_sku FROM products p JOIN categories c ON p.category_id = c.id JOIN suppliers s ON p.supplier_id = s.id" \
    --replace

# Step 4: Generate output files
mkdir -p /app/output

# Product count
sqlite-utils /app/catalog.db "SELECT count(*) FROM products" --csv --no-headers \
    > /app/output/product_count.txt

# Category distribution CSV
sqlite-utils /app/catalog.db \
    "SELECT c.name, c.subcategory, count(*) as product_count FROM products p JOIN categories c ON p.category_id = c.id GROUP BY c.name, c.subcategory ORDER BY c.name, c.subcategory" \
    --csv > /app/output/category_distribution.csv

# Supplier ranking JSON
sqlite-utils /app/catalog.db \
    "SELECT s.canonical_name as name, count(*) as product_count FROM products p JOIN suppliers s ON p.supplier_id = s.id GROUP BY s.canonical_name ORDER BY product_count DESC, name ASC" \
    > /app/output/supplier_ranking.json

# FTS search results
sqlite-utils search /app/catalog.db products "wireless" \
    > /app/output/fts_results.json

# Quarantine report
sqlite-utils /app/catalog.db \
    "SELECT source_sku, product_name, reason FROM quarantined_records" \
    > /app/output/quarantine_report.json

echo "Pipeline complete. Output files in /app/output/"
