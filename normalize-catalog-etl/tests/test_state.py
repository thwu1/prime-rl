"""
"""
import sqlite3
import json
import os
import csv
import re
import pytest

DB_PATH = "/app/catalog.db"


@pytest.fixture
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# -- Table Structure -------------------------------------------------------------


class TestTableStructure:
    def test_products_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "products" in tables

    def test_categories_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "categories" in tables

    def test_suppliers_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "suppliers" in tables

    def test_product_tags_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "product_tags" in tables

    def test_quarantined_records_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "quarantined_records" in tables

    def test_price_history_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "price_history" in tables

    def test_category_analytics_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "category_analytics" in tables

    def test_products_has_required_columns(self, db):
        cols = {r[1] for r in db.execute("PRAGMA table_info(products)").fetchall()}
        required = {
            "product_name", "description", "price_usd", "category_id",
            "supplier_id", "received_date", "quantity", "is_active", "source_sku",
        }
        missing = required - cols
        assert not missing, f"products table missing columns: {missing}"

    def test_categories_has_required_columns(self, db):
        cols = {r[1] for r in db.execute("PRAGMA table_info(categories)").fetchall()}
        assert "name" in cols and "subcategory" in cols

    def test_suppliers_has_required_columns(self, db):
        cols = {r[1] for r in db.execute("PRAGMA table_info(suppliers)").fetchall()}
        assert "canonical_name" in cols
        assert "country" in cols
        assert "rating" in cols

    def test_quarantined_has_required_columns(self, db):
        cols = {r[1] for r in db.execute(
            "PRAGMA table_info(quarantined_records)"
        ).fetchall()}
        assert "source_sku" in cols
        assert "product_name" in cols
        assert "reason" in cols

    def test_price_history_has_required_columns(self, db):
        cols = {r[1] for r in db.execute(
            "PRAGMA table_info(price_history)"
        ).fetchall()}
        required = {
            "source_sku", "product_name", "original_price",
            "original_currency", "fx_rate_applied", "price_usd",
            "source_feed", "received_date", "is_catalog_entry",
        }
        missing = required - cols
        assert not missing, f"price_history missing columns: {missing}"

    def test_category_analytics_has_required_columns(self, db):
        cols = {r[1] for r in db.execute(
            "PRAGMA table_info(category_analytics)"
        ).fetchall()}
        required = {
            "category", "subcategory", "product_count", "avg_price_usd",
            "min_price_usd", "max_price_usd", "total_quantity",
            "distinct_supplier_count",
        }
        missing = required - cols
        assert not missing, f"category_analytics missing columns: {missing}"


# -- Row Counts ------------------------------------------------------------------


class TestRowCounts:
    def test_products_count(self, db):
        count = db.execute("SELECT count(*) FROM products").fetchone()[0]
        assert count == 26, f"Expected 26 products, got {count}"

    def test_categories_count(self, db):
        count = db.execute("SELECT count(*) FROM categories").fetchone()[0]
        assert count == 13, f"Expected 13 categories, got {count}"

    def test_suppliers_count(self, db):
        count = db.execute("SELECT count(*) FROM suppliers").fetchone()[0]
        assert count == 8, f"Expected 8 suppliers, got {count}"

    def test_product_tags_count(self, db):
        count = db.execute("SELECT count(*) FROM product_tags").fetchone()[0]
        assert count == 89, f"Expected 89 product-tag pairs, got {count}"

    def test_quarantined_count(self, db):
        count = db.execute("SELECT count(*) FROM quarantined_records").fetchone()[0]
        assert count == 2, f"Expected 2 quarantined records, got {count}"

    def test_price_history_count(self, db):
        count = db.execute("SELECT count(*) FROM price_history").fetchone()[0]
        assert count == 30, f"Expected 30 price history rows, got {count}"

    def test_category_analytics_count(self, db):
        count = db.execute("SELECT count(*) FROM category_analytics").fetchone()[0]
        assert count == 13, f"Expected 13 category analytics rows, got {count}"


# -- Deduplication ---------------------------------------------------------------


class TestDeduplication:
    """Products with same REF code across feeds: most recent date wins."""

    def test_p1001_winner_is_beta(self, db):
        """REF:P1001 -- B001 (Apr 1) should beat A001 (Jan 15)."""
        row = db.execute(
            "SELECT product_name, source_sku, received_date FROM products "
            "WHERE source_sku = 'B001'"
        ).fetchone()
        assert row is not None, "B001 not found -- P1001 dup resolution failed"
        assert row["product_name"] == "Pro Wireless Earbuds"
        assert row["received_date"] == "2024-04-01"

    def test_p1002_winner_is_gamma(self, db):
        """REF:P1002 -- G001 (May 15) should beat A002 (Feb 28)."""
        row = db.execute(
            "SELECT product_name, source_sku, received_date FROM products "
            "WHERE source_sku = 'G001'"
        ).fetchone()
        assert row is not None, "G001 not found -- P1002 dup resolution failed"
        assert row["product_name"] == "SmartWatch X200 Pro"
        assert row["received_date"] == "2024-05-15"

    def test_p1003_winner_is_beta(self, db):
        """REF:P1003 -- B008 (Jun 1) should beat A005 (Apr 22)."""
        row = db.execute(
            "SELECT product_name, source_sku, received_date FROM products "
            "WHERE source_sku = 'B008'"
        ).fetchone()
        assert row is not None, "B008 not found -- P1003 dup resolution failed"
        assert row["product_name"] == "HD Action Camera"
        assert row["received_date"] == "2024-06-01"

    def test_p1004_winner_is_alpha(self, db):
        """REF:P1004 -- A008 (Mar 30) should beat G008 (Feb 10)."""
        row = db.execute(
            "SELECT product_name, source_sku, received_date FROM products "
            "WHERE source_sku = 'A008'"
        ).fetchone()
        assert row is not None, "A008 not found -- P1004 dup resolution failed"
        assert row["product_name"] == "Bluetooth Speaker Waterproof"
        assert row["received_date"] == "2024-03-30"

    def test_loser_a001_not_in_products(self, db):
        """A001 lost to B001 for P1001 -- should not be in products."""
        row = db.execute(
            "SELECT count(*) FROM products WHERE source_sku = 'A001'"
        ).fetchone()[0]
        assert row == 0, "A001 should not be in products (lost dup to B001)"

    def test_loser_a002_not_in_products(self, db):
        row = db.execute(
            "SELECT count(*) FROM products WHERE source_sku = 'A002'"
        ).fetchone()[0]
        assert row == 0, "A002 should not be in products (lost dup to G001)"

    def test_loser_a005_not_in_products(self, db):
        row = db.execute(
            "SELECT count(*) FROM products WHERE source_sku = 'A005'"
        ).fetchone()[0]
        assert row == 0, "A005 should not be in products (lost dup to B008)"

    def test_loser_g008_not_in_products(self, db):
        row = db.execute(
            "SELECT count(*) FROM products WHERE source_sku = 'G008'"
        ).fetchone()[0]
        assert row == 0, "G008 should not be in products (lost dup to A008)"


# -- Tag Merging -----------------------------------------------------------------


class TestTagMerging:
    def test_p1001_merged_tags(self, db):
        """B001 winner should have union of A001 + B001 tags = 6."""
        count = db.execute(
            "SELECT count(*) FROM product_tags WHERE product_id = "
            "(SELECT id FROM products WHERE source_sku = 'B001')"
        ).fetchone()[0]
        assert count == 6, f"P1001 should have 6 merged tags, got {count}"

    def test_p1001_has_portable_from_alpha(self, db):
        """'portable' tag came from A001 (alpha), should survive merge."""
        tags = {r[0] for r in db.execute(
            "SELECT tag FROM product_tags WHERE product_id = "
            "(SELECT id FROM products WHERE source_sku = 'B001')"
        ).fetchall()}
        assert "portable" in tags, f"Tag 'portable' (from alpha) missing. Tags: {tags}"

    def test_p1001_has_anc_from_beta(self, db):
        """'anc' tag came from B001 (beta), should survive merge."""
        tags = {r[0] for r in db.execute(
            "SELECT tag FROM product_tags WHERE product_id = "
            "(SELECT id FROM products WHERE source_sku = 'B001')"
        ).fetchall()}
        assert "anc" in tags, f"Tag 'anc' (from beta) missing. Tags: {tags}"

    def test_p1004_merged_tags(self, db):
        """A008 winner should have union of A008 + G008 tags = 6."""
        count = db.execute(
            "SELECT count(*) FROM product_tags WHERE product_id = "
            "(SELECT id FROM products WHERE source_sku = 'A008')"
        ).fetchone()[0]
        assert count == 6, f"P1004 should have 6 merged tags, got {count}"

    def test_p1004_has_speaker_from_gamma(self, db):
        """'speaker' tag came from G008 (gamma), should survive merge."""
        tags = {r[0] for r in db.execute(
            "SELECT tag FROM product_tags WHERE product_id = "
            "(SELECT id FROM products WHERE source_sku = 'A008')"
        ).fetchall()}
        assert "speaker" in tags, f"Tag 'speaker' (from gamma) missing. Tags: {tags}"


# -- Temporal FX Conversion (with corrections) -----------------------------------


class TestTemporalFxConversion:
    """Prices must use corrected FX rates where applicable, falling back to
    fx_history when no correction exists for that currency/date range."""

    def test_eur_q1_corrected_rate(self, db):
        """A003: EUR 136.36, Mar 10 (Q1) -> corrected rate 1.09 -> $148.63"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'A003'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 148.63) < 0.02, f"Expected ~148.63, got {row[0]}"

    def test_eur_q2_rate(self, db):
        """A009: EUR 179.99, Apr 15 (Q2) -> base rate 1.10 -> $197.99"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'A009'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 197.99) < 0.02, f"Expected ~197.99, got {row[0]}"

    def test_gbp_q1_rate(self, db):
        """B002: GBP 199.00, Jan 15 (Q1) -> rate 1.25 -> $248.75"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'B002'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 248.75) < 0.02, f"Expected ~248.75, got {row[0]}"

    def test_gbp_q2_rate(self, db):
        """B005: GBP 1299.00, Apr 6 (Q2) -> rate 1.27 -> $1649.73"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'B005'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 1649.73) < 0.02, f"Expected ~1649.73, got {row[0]}"

    def test_usd_no_conversion(self, db):
        """B001 (USD 79.99) should remain 79.99 -- no FX conversion."""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'B001'"
        ).fetchone()
        assert abs(row[0] - 79.99) < 0.01

    def test_gamma_usd_no_conversion(self, db):
        """G002 (USD 179.99) should remain 179.99."""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'G002'"
        ).fetchone()
        assert abs(row[0] - 179.99) < 0.01

    def test_eur_q1_corrected_drill(self, db):
        """A007: EUR 81.81, Feb 14 (Q1) -> corrected rate 1.09 -> $89.17"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'A007'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 89.17) < 0.02, f"Expected ~89.17, got {row[0]}"

    def test_gbp_q2_textbook(self, db):
        """B010: GBP 79.00, Apr 2 (Q2) -> rate 1.27 -> $100.33"""
        row = db.execute(
            "SELECT price_usd FROM products WHERE source_sku = 'B010'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 100.33) < 0.02, f"Expected ~100.33, got {row[0]}"


# -- Supplier Alias Resolution ---------------------------------------------------


class TestSupplierResolution:
    def test_all_supplier_names(self, db):
        names = {r[0] for r in db.execute(
            "SELECT canonical_name FROM suppliers"
        ).fetchall()}
        expected = {
            "SoundTech Inc", "TechWear Ltd", "HomeGoods GmbH", "FitLife Corp",
            "GadgetMax Co", "BookWorld Inc", "QualityTools AG", "SportsPro SA",
        }
        assert names == expected, f"Missing suppliers: {expected - names}"

    def test_alias_soundtech_inc(self, db):
        """A008's 'SOUNDTECH INC' should resolve to SoundTech Inc."""
        row = db.execute(
            "SELECT s.canonical_name FROM products p "
            "JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.source_sku = 'A008'"
        ).fetchone()
        assert row is not None
        assert row[0] == "SoundTech Inc"

    def test_alias_techwear(self, db):
        """G001's 'TechWear' should resolve to TechWear Ltd."""
        row = db.execute(
            "SELECT s.canonical_name FROM products p "
            "JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.source_sku = 'G001'"
        ).fetchone()
        assert row is not None
        assert row[0] == "TechWear Ltd"

    def test_alias_sports_pro_sa(self, db):
        """B007's 'Sports Pro SA' should resolve to SportsPro SA."""
        row = db.execute(
            "SELECT s.canonical_name FROM products p "
            "JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.source_sku = 'B007'"
        ).fetchone()
        assert row is not None
        assert row[0] == "SportsPro SA"

    def test_alias_home_goods_gmbh(self, db):
        """G010's 'Home Goods GmbH' should resolve to HomeGoods GmbH."""
        row = db.execute(
            "SELECT s.canonical_name FROM products p "
            "JOIN suppliers s ON p.supplier_id = s.id "
            "WHERE p.source_sku = 'G010'"
        ).fetchone()
        assert row is not None
        assert row[0] == "HomeGoods GmbH"

    def test_supplier_country(self, db):
        row = db.execute(
            "SELECT country FROM suppliers WHERE canonical_name = 'SoundTech Inc'"
        ).fetchone()
        assert row[0] == "US"

    def test_supplier_rating(self, db):
        row = db.execute(
            "SELECT rating FROM suppliers WHERE canonical_name = 'BookWorld Inc'"
        ).fetchone()
        assert abs(row[0] - 4.7) < 0.01


# -- Date Normalization ----------------------------------------------------------


class TestDateNormalization:
    def test_all_dates_iso_format(self, db):
        dates = db.execute("SELECT received_date FROM products").fetchall()
        for row in dates:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]), \
                f"Date not in ISO 8601 format: '{row[0]}'"

    def test_alpha_european_date(self, db):
        """Alpha format: 10.03.2024 -> 2024-03-10"""
        row = db.execute(
            "SELECT received_date FROM products WHERE source_sku = 'A003'"
        ).fetchone()
        assert row[0] == "2024-03-10"

    def test_beta_unix_timestamp(self, db):
        """Beta format: Unix timestamp 1711929600 -> 2024-04-01"""
        row = db.execute(
            "SELECT received_date FROM products WHERE source_sku = 'B001'"
        ).fetchone()
        assert row[0] == "2024-04-01"

    def test_gamma_slash_date(self, db):
        """Gamma format: 2024/05/15 -> 2024-05-15"""
        row = db.execute(
            "SELECT received_date FROM products WHERE source_sku = 'G001'"
        ).fetchone()
        assert row[0] == "2024-05-15"

    def test_alpha_another_date(self, db):
        """Alpha: 05.01.2024 -> 2024-01-05"""
        row = db.execute(
            "SELECT received_date FROM products WHERE source_sku = 'A004'"
        ).fetchone()
        assert row[0] == "2024-01-05"


# -- Quarantine ------------------------------------------------------------------


class TestQuarantine:
    def test_negative_quantity_quarantined(self, db):
        """A011 has quantity=-5, should be quarantined."""
        row = db.execute(
            "SELECT product_name FROM quarantined_records "
            "WHERE source_sku = 'A011'"
        ).fetchone()
        assert row is not None, "A011 not found in quarantined_records"
        assert row[0] == "Garden Hose Expandable"

    def test_zero_price_quarantined(self, db):
        """A012 has price=0.00, should be quarantined."""
        row = db.execute(
            "SELECT product_name FROM quarantined_records "
            "WHERE source_sku = 'A012'"
        ).fetchone()
        assert row is not None, "A012 not found in quarantined_records"
        assert row[0] == "Fitness Tracker Band"

    def test_quarantined_not_in_products(self, db):
        """Quarantined records should NOT appear in products table."""
        count = db.execute(
            "SELECT count(*) FROM products WHERE source_sku IN ('A011', 'A012')"
        ).fetchone()[0]
        assert count == 0, "Quarantined records found in products table"


# -- Category Normalization ------------------------------------------------------


class TestCategories:
    def test_category_names_title_case(self, db):
        cats = {r[0] for r in db.execute(
            "SELECT DISTINCT name FROM categories"
        ).fetchall()}
        expected = {"Books", "Electronics", "Home & Garden", "Sports"}
        assert cats == expected, f"Expected {expected}, got {cats}"

    def test_subcategory_names(self, db):
        subcats = {r[0] for r in db.execute(
            "SELECT DISTINCT subcategory FROM categories"
        ).fetchall()}
        expected = {
            "Audio", "Wearables", "Cameras", "Smart Home", "Accessories",
            "Kitchen", "Tools", "Fitness", "Outdoor Sports", "Team Sports",
            "Fiction", "Non-Fiction", "Technical",
        }
        assert subcats == expected, f"Subcategory mismatch: {expected - subcats} missing"

    def test_unique_category_subcategory_pairs(self, db):
        total = db.execute("SELECT count(*) FROM categories").fetchone()[0]
        unique = db.execute(
            "SELECT count(*) FROM (SELECT DISTINCT name, subcategory FROM categories)"
        ).fetchone()[0]
        assert total == unique

    def test_product_category_join(self, db):
        """A003 should be in Home & Garden / Kitchen."""
        row = db.execute(
            "SELECT c.name, c.subcategory FROM products p "
            "JOIN categories c ON p.category_id = c.id "
            "WHERE p.source_sku = 'A003'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Home & Garden"
        assert row[1] == "Kitchen"

    def test_gamma_category_parsing(self, db):
        """G004 category 'sports::team sports' -> Sports / Team Sports."""
        row = db.execute(
            "SELECT c.name, c.subcategory FROM products p "
            "JOIN categories c ON p.category_id = c.id "
            "WHERE p.source_sku = 'G004'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Sports"
        assert row[1] == "Team Sports"


# -- Field Cleaning --------------------------------------------------------------


class TestFieldCleaning:
    def test_product_names_trimmed(self, db):
        names = db.execute("SELECT product_name FROM products").fetchall()
        for row in names:
            assert row[0] == row[0].strip(), f"Name has whitespace: '{row[0]}'"

    def test_is_active_only_zero_one(self, db):
        vals = {r[0] for r in db.execute(
            "SELECT DISTINCT is_active FROM products"
        ).fetchall()}
        assert vals <= {0, 1}, f"is_active has unexpected values: {vals}"

    def test_inactive_count(self, db):
        """B006 (Philosophy of Mind) and G005 (Mystery Novel Collection) are inactive."""
        count = db.execute(
            "SELECT count(*) FROM products WHERE is_active = 0"
        ).fetchone()[0]
        assert count == 2, f"Expected 2 inactive products, got {count}"

    def test_quantities_are_integers(self, db):
        qtys = db.execute("SELECT quantity FROM products").fetchall()
        for row in qtys:
            assert isinstance(row[0], int), f"Quantity not integer: {row[0]}"


# -- Relationships ---------------------------------------------------------------


class TestRelationships:
    def test_all_products_have_valid_category(self, db):
        orphans = db.execute(
            "SELECT count(*) FROM products "
            "WHERE category_id NOT IN (SELECT id FROM categories)"
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} products have invalid category_id"

    def test_all_products_have_valid_supplier(self, db):
        orphans = db.execute(
            "SELECT count(*) FROM products "
            "WHERE supplier_id NOT IN (SELECT id FROM suppliers)"
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} products have invalid supplier_id"

    def test_all_tags_have_valid_product(self, db):
        orphans = db.execute(
            "SELECT count(*) FROM product_tags "
            "WHERE product_id NOT IN (SELECT id FROM products)"
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} tags reference invalid product_id"


# -- FTS5 ------------------------------------------------------------------------


class TestFTS:
    def test_fts_table_exists(self, db):
        fts = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'products_fts%'"
        ).fetchall()
        assert len(fts) > 0, "No FTS table found for products"

    def test_fts5_engine(self, db):
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='products_fts'"
        ).fetchone()
        assert row is not None, "products_fts table not found"
        assert "fts5" in row[0].lower(), f"Expected FTS5, got: {row[0]}"

    def test_fts_porter_tokenizer(self, db):
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='products_fts'"
        ).fetchone()
        assert row is not None
        assert "porter" in row[0].lower(), f"Expected porter tokenizer, got: {row[0]}"

    def test_fts_search_wireless(self, db):
        results = db.execute(
            "SELECT * FROM products_fts WHERE products_fts MATCH 'wireless'"
        ).fetchall()
        assert len(results) == 3, \
            f"FTS 'wireless' should return 3, got {len(results)}"


# -- View ------------------------------------------------------------------------


class TestView:
    def test_product_summary_view_exists(self, db):
        views = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()]
        assert "product_summary" in views, f"Views: {views}"

    def test_product_summary_row_count(self, db):
        count = db.execute("SELECT count(*) FROM product_summary").fetchone()[0]
        assert count == 26

    def test_product_summary_category(self, db):
        row = db.execute(
            "SELECT category, subcategory FROM product_summary "
            "WHERE source_sku = 'B001'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Electronics"
        assert row[1] == "Audio"

    def test_product_summary_supplier(self, db):
        row = db.execute(
            "SELECT supplier_name, supplier_country FROM product_summary "
            "WHERE source_sku = 'B001'"
        ).fetchone()
        assert row is not None
        assert row[0] == "SoundTech Inc"
        assert row[1] == "US"


# -- Output Files ----------------------------------------------------------------


class TestOutputFiles:
    def test_product_count_file(self):
        path = "/app/output/product_count.txt"
        assert os.path.exists(path), f"File not found: {path}"
        with open(path) as f:
            content = f.read().strip()
        assert content == "26", f"Expected '26', got '{content}'"

    def test_category_distribution_exists(self):
        path = "/app/output/category_distribution.csv"
        assert os.path.exists(path), f"File not found: {path}"

    def test_category_distribution_row_count(self):
        path = "/app/output/category_distribution.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 13, f"Expected 13 data rows, got {len(rows)}"

    def test_category_distribution_specific(self):
        path = "/app/output/category_distribution.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        hg_kitchen = [
            r for r in rows
            if r.get("name") == "Home & Garden" and r.get("subcategory") == "Kitchen"
        ]
        assert len(hg_kitchen) == 1, "Home & Garden/Kitchen not found"
        assert int(hg_kitchen[0]["product_count"]) == 4

    def test_supplier_ranking_json(self):
        path = "/app/output/supplier_ranking.json"
        assert os.path.exists(path), f"File not found: {path}"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 8, f"Expected 8 suppliers, got {len(data)}"
        # Top supplier is BookWorld Inc with 5
        assert data[0]["product_count"] == 5, \
            f"Top supplier should have 5 products, got {data[0]}"
        assert data[0]["name"] == "BookWorld Inc"

    def test_fts_results_json(self):
        path = "/app/output/fts_results.json"
        assert os.path.exists(path), f"File not found: {path}"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 3, \
            f"FTS 'wireless' should return 3, got {len(data)}"

    def test_quarantine_report_json(self):
        path = "/app/output/quarantine_report.json"
        assert os.path.exists(path), f"File not found: {path}"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2
        skus = {r["source_sku"] for r in data}
        assert "A011" in skus and "A012" in skus


# -- Price History (audit trail) -------------------------------------------------


class TestPriceHistory:
    """price_history must record every valid price observation from all feeds,
    including records eliminated during deduplication."""

    def test_dedup_loser_recorded(self, db):
        """A001 was a dedup loser (P1001) but must be in price_history."""
        row = db.execute(
            "SELECT * FROM price_history WHERE source_sku = 'A001'"
        ).fetchone()
        assert row is not None, "A001 missing from price_history"
        assert row["is_catalog_entry"] == 0
        assert row["source_feed"] == "alpha"

    def test_dedup_winner_recorded(self, db):
        """B001 was the dedup winner (P1001) and must be in price_history."""
        row = db.execute(
            "SELECT * FROM price_history WHERE source_sku = 'B001'"
        ).fetchone()
        assert row is not None, "B001 missing from price_history"
        assert row["is_catalog_entry"] == 1
        assert row["source_feed"] == "beta"

    def test_corrected_fx_rate_in_history(self, db):
        """A003 should use corrected EUR Q1 rate of 1.09 in price_history."""
        row = db.execute(
            "SELECT fx_rate_applied, price_usd FROM price_history "
            "WHERE source_sku = 'A003'"
        ).fetchone()
        assert row is not None
        assert abs(row["fx_rate_applied"] - 1.09) < 0.001, \
            f"Expected corrected rate 1.09, got {row['fx_rate_applied']}"
        assert abs(row["price_usd"] - 148.63) < 0.02

    def test_usd_rate_in_history(self, db):
        """G002 is USD and should have fx_rate_applied=1.0."""
        row = db.execute(
            "SELECT fx_rate_applied, price_usd FROM price_history "
            "WHERE source_sku = 'G002'"
        ).fetchone()
        assert abs(row["fx_rate_applied"] - 1.0) < 0.001
        assert abs(row["price_usd"] - 179.99) < 0.01

    def test_quarantined_not_in_history(self, db):
        """Quarantined records (A011, A012) must NOT appear in price_history."""
        count = db.execute(
            "SELECT count(*) FROM price_history "
            "WHERE source_sku IN ('A011', 'A012')"
        ).fetchone()[0]
        assert count == 0, "Quarantined records found in price_history"

    def test_catalog_vs_noncatalog_counts(self, db):
        """26 catalog entries (dedup winners), 4 non-catalog (dedup losers)."""
        catalog = db.execute(
            "SELECT count(*) FROM price_history WHERE is_catalog_entry = 1"
        ).fetchone()[0]
        non_catalog = db.execute(
            "SELECT count(*) FROM price_history WHERE is_catalog_entry = 0"
        ).fetchone()[0]
        assert catalog == 26, f"Expected 26 catalog entries, got {catalog}"
        assert non_catalog == 4, f"Expected 4 non-catalog entries, got {non_catalog}"

    def test_loser_a005_fx_rate(self, db):
        """A005: EUR in Q2 -> should use base rate 1.10 (no correction)."""
        row = db.execute(
            "SELECT fx_rate_applied, original_currency, received_date "
            "FROM price_history WHERE source_sku = 'A005'"
        ).fetchone()
        assert row is not None, "A005 missing from price_history"
        assert abs(row["fx_rate_applied"] - 1.10) < 0.001, \
            f"A005 Q2 EUR should use base rate 1.10, got {row['fx_rate_applied']}"


# -- Category Analytics (materialized) -------------------------------------------


class TestCategoryAnalytics:
    """category_analytics must be a materialized table computed from final
    catalog data, with correct aggregations per category/subcategory."""

    def test_all_categories_present(self, db):
        categories = db.execute(
            "SELECT category || '/' || subcategory FROM category_analytics "
            "ORDER BY 1"
        ).fetchall()
        expected = [
            "Books/Fiction", "Books/Non-Fiction", "Books/Technical",
            "Electronics/Accessories", "Electronics/Audio",
            "Electronics/Cameras", "Electronics/Smart Home",
            "Electronics/Wearables",
            "Home & Garden/Kitchen", "Home & Garden/Tools",
            "Sports/Fitness", "Sports/Outdoor Sports", "Sports/Team Sports",
        ]
        actual = [r[0] for r in categories]
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_kitchen_analytics(self, db):
        """Home & Garden / Kitchen: 4 products, all from HomeGoods GmbH."""
        row = db.execute(
            "SELECT * FROM category_analytics "
            "WHERE category = 'Home & Garden' AND subcategory = 'Kitchen'"
        ).fetchone()
        assert row is not None
        assert row["product_count"] == 4
        assert abs(row["min_price_usd"] - 39.99) < 0.01
        assert abs(row["max_price_usd"] - 598.41) < 0.10
        assert row["total_quantity"] == 535
        assert row["distinct_supplier_count"] == 1

    def test_audio_analytics(self, db):
        """Electronics / Audio: 3 products (B001, A008, B002), 1 supplier."""
        row = db.execute(
            "SELECT * FROM category_analytics "
            "WHERE category = 'Electronics' AND subcategory = 'Audio'"
        ).fetchone()
        assert row is not None
        assert row["product_count"] == 3
        assert abs(row["min_price_usd"] - 59.45) < 0.10
        assert abs(row["max_price_usd"] - 248.75) < 0.01
        assert row["total_quantity"] == 360
        assert row["distinct_supplier_count"] == 1

    def test_fitness_analytics(self, db):
        """Sports / Fitness: 4 products, total qty 780."""
        row = db.execute(
            "SELECT * FROM category_analytics "
            "WHERE category = 'Sports' AND subcategory = 'Fitness'"
        ).fetchone()
        assert row is not None
        assert row["product_count"] == 4
        assert row["total_quantity"] == 780
        assert abs(row["min_price_usd"] - 21.79) < 0.10
        assert abs(row["max_price_usd"] - 349.99) < 0.01

    def test_outdoor_sports_analytics(self, db):
        """Sports / Outdoor Sports: 3 products (B005, B007, G007)."""
        row = db.execute(
            "SELECT * FROM category_analytics "
            "WHERE category = 'Sports' AND subcategory = 'Outdoor Sports'"
        ).fetchone()
        assert row is not None
        assert row["product_count"] == 3
        assert row["total_quantity"] == 125
        assert abs(row["max_price_usd"] - 1649.73) < 0.02
        assert row["distinct_supplier_count"] == 1
