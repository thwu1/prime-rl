Three product data feeds in `/app/feeds/` must be consolidated into a single normalized catalog at `/app/catalog.db`. Each feed uses a different file format, field encoding convention, delimiter scheme, and date representation — inspect the files to determine their structure before parsing.

A reference database at `/app/reference.db` provides lookup tables for currency conversion, retroactive rate corrections, canonical supplier identities, and supplier name aliases. Inspect its schema to understand all available tables and how they interact — corrections supersede base rates when a matching currency and date range is found.

## Target Schema in `/app/catalog.db`

- **`categories`**: `id` INTEGER PRIMARY KEY, `name` TEXT NOT NULL, `subcategory` TEXT NOT NULL, UNIQUE(name, subcategory). Both title-cased.
- **`suppliers`**: `id` INTEGER PRIMARY KEY, `canonical_name` TEXT NOT NULL UNIQUE, `country` TEXT, `rating` REAL — populated from `reference.db` for matched suppliers
- **`products`**: `id` INTEGER PRIMARY KEY, `product_name` TEXT NOT NULL, `description` TEXT, `price_usd` REAL NOT NULL (rounded to 2 decimal places), `category_id` INTEGER REFERENCES categories(id), `supplier_id` INTEGER REFERENCES suppliers(id), `received_date` TEXT NOT NULL (ISO 8601 YYYY-MM-DD), `quantity` INTEGER NOT NULL, `is_active` INTEGER NOT NULL (0/1), `source_sku` TEXT NOT NULL
- **`product_tags`**: `product_id` INTEGER REFERENCES products(id), `tag` TEXT NOT NULL — one row per tag, deduplicated per product
- **`quarantined_records`**: `source_sku` TEXT, `product_name` TEXT, `reason` TEXT — records with non-positive prices or negative quantities
- **`price_history`**: `id` INTEGER PRIMARY KEY, `source_sku` TEXT NOT NULL, `product_name` TEXT NOT NULL, `original_price` REAL NOT NULL, `original_currency` TEXT NOT NULL, `fx_rate_applied` REAL NOT NULL, `price_usd` REAL NOT NULL (rounded to 2dp), `source_feed` TEXT NOT NULL, `received_date` TEXT NOT NULL, `is_catalog_entry` INTEGER NOT NULL (1 if this observation became the final catalog product, 0 if eliminated during deduplication) — one row per valid (non-quarantined) price observation from every feed, preserving the full audit trail including records lost to deduplication
- **`category_analytics`**: `category` TEXT NOT NULL, `subcategory` TEXT NOT NULL, `product_count` INTEGER NOT NULL, `avg_price_usd` REAL NOT NULL (rounded to 2dp), `min_price_usd` REAL NOT NULL, `max_price_usd` REAL NOT NULL, `total_quantity` INTEGER NOT NULL, `distinct_supplier_count` INTEGER NOT NULL, PRIMARY KEY(category, subcategory) — materialized analytics computed from the final catalog data

## Deduplication

Products sharing a reference code (embedded in descriptions) across feeds are duplicates. Keep the record with the most recent `received_date`; merge tags as the union across all versions of that product.

## Additional Requirements

- FTS5 full-text search on `products(product_name, description)` with porter tokenizer
- SQL view `product_summary` with columns: `id`, `product_name`, `price_usd`, `category` (categories.name), `subcategory`, `supplier_name` (suppliers.canonical_name), `supplier_country` (suppliers.country), `received_date`, `quantity`, `is_active`, `source_sku`
- Output files in `/app/output/`:
  - `product_count.txt` — integer count of products rows
  - `category_distribution.csv` — CSV headers `name,subcategory,product_count`, sorted by name then subcategory
  - `supplier_ranking.json` — JSON array of `{"name": ..., "product_count": ...}`, sorted by count desc then name asc
  - `fts_results.json` — JSON array from FTS search for `wireless`
  - `quarantine_report.json` — JSON array of all quarantined records

`sqlite-utils` is pre-installed.