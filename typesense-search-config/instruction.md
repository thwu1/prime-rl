A Typesense search engine is installed at `/usr/local/bin/typesense-server`. A pre-configured instance with data directory `/app/typesense-data` and admin API key `typesense_bench_admin_key` contains three collections (`brands`, `products`, `reviews`) populated with product catalog data. Raw JSONL data files are at `/app/data/`. The server listens on port 8108.

The system was deployed with multiple configuration defects across its schema, search features, and access control. Several search operations that should work are failing or returning incorrect results. Diagnose and remediate all issues so the system meets these requirements:

**Cross-collection JOINs**: Querying products via `$brands(...)` must include brand data (name, country) through the `brand_id` field. Filtering products by `$brands(is_premium:=true)` must return exactly 6 results from brands TechPro, EuroGadget, and NovaCorp. Querying products via `$reviews(...)` must include review data through the `product_id` field.

**Geo-search**: Filtering products by `location:(37.7749, -122.4194, 100 km)` must return exactly 4 products: prod_1, prod_5, prod_6, prod_10.

**Faceted search**: Faceting on `category` must return counts of 7 for `electronics` and 3 for `accessories`.

**Synonym expansion**: `laptop`, `notebook`, and `portable computer` must be fully interchangeable multi-way synonyms. `mobile` must expand one-way to also match `phone` and `smartphone`, but searching `phone` must NOT expand to match `mobile`-only products.

**Curation**: Override `featured_override` must pin prod_5 at position 1 and exclude prod_4 only when the search query is exactly `featured`. Queries that merely contain the word "featured" (e.g. `featured deals`) must NOT trigger this override.

**Access control**: `/app/search_only_key.txt` must contain an API key limited to `documents:search` on the `products` collection only. This key must be denied write operations and must not work on other collections such as `brands`.

The Typesense server must be running on port 8108 when verification occurs.