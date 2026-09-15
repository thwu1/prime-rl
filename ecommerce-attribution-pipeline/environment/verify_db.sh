#!/bin/bash
# Verify all 7 tables exist in the ecommerce database
python3 -c "
import duckdb
conn = duckdb.connect('/app/ecommerce.duckdb', read_only=True)
tables = [r[0] for r in conn.execute(\"SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name\").fetchall()]
print('Tables found:', tables)
assert len(tables) == 7, f'Expected 7 tables, got {len(tables)}: {tables}'
for t in ['users', 'products', 'sessions', 'orders', 'order_items', 'refunds', 'promotional_credits']:
    assert t in tables, f'Missing table: {t}'
    cnt = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t}: {cnt} rows')
    assert cnt > 0, f'Table {t} is empty!'
conn.close()
print('Database verification passed.')
"
