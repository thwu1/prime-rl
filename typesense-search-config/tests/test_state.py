"""
"""
import pytest
import requests
import os
import time

BASE_URL = "http://localhost:8108"
ADMIN_KEY = "typesense_bench_admin_key"
HEADERS = {"X-TYPESENSE-API-KEY": ADMIN_KEY}


@pytest.fixture(scope="session", autouse=True)
def wait_for_typesense():
    for attempt in range(15):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=5)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    pytest.fail("Typesense server is not running at localhost:8108")


def api_get(path, params=None):
    return requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params)


def api_post(path, data):
    return requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=data)


# ── Forward JOIN Tests ──────────────────────────────────────────────────────

class TestForwardJoin:

    def test_product_includes_brand_data(self):
        """Forward JOIN: product query must include brand name and country."""
        resp = api_post("/multi_search", {
            "searches": [{
                "collection": "products",
                "q": "*",
                "query_by": "title",
                "filter_by": "id:=prod_1",
                "include_fields": "$brands(name,country)"
            }]
        })
        data = resp.json()
        hits = data["results"][0]["hits"]
        assert len(hits) == 1
        doc = hits[0]["document"]
        assert "brands" in doc, "Brand data not joined — brand_id may lack reference to brands.id"
        assert doc["brands"]["name"] == "TechPro"
        assert doc["brands"]["country"] == "US"

    def test_join_filter_premium_brands(self):
        """JOIN filter: products from premium brands must return exactly 6."""
        resp = api_post("/multi_search", {
            "searches": [{
                "collection": "products",
                "q": "*",
                "query_by": "title",
                "filter_by": "$brands(is_premium:=true)",
                "include_fields": "$brands(name)"
            }]
        })
        data = resp.json()
        hits = data["results"][0]["hits"]
        assert len(hits) == 6, f"Expected 6 premium-brand products, got {len(hits)}"
        brand_names = {h["document"]["brands"]["name"] for h in hits}
        assert brand_names == {"TechPro", "EuroGadget", "NovaCorp"}


# ── Reverse JOIN Tests ──────────────────────────────────────────────────────

class TestReverseJoin:

    def test_product_includes_review_data(self):
        """Reverse JOIN: querying products must be able to include review data."""
        resp = api_post("/multi_search", {
            "searches": [{
                "collection": "products",
                "q": "*",
                "query_by": "title",
                "filter_by": "$reviews(id: *)",
                "include_fields": "$reviews(rating,text)",
                "per_page": "250"
            }]
        })
        data = resp.json()
        hits = data["results"][0]["hits"]
        assert len(hits) >= 1, "No products with reviews found — product_id may lack reference"
        found_reviews = any("reviews" in h["document"] for h in hits)
        assert found_reviews, "Review data not joined into any product document"


# ── Geo-Search Tests ────────────────────────────────────────────────────────

class TestGeoSearch:

    def test_geo_radius_returns_four_bay_area_products(self):
        """Products within 100km of SF must be exactly prod_1, prod_5, prod_6, prod_10."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "*",
            "query_by": "title",
            "filter_by": "location:(37.7749, -122.4194, 100 km)"
        })
        data = resp.json()
        ids = sorted([h["document"]["id"] for h in data["hits"]])
        assert ids == ["prod_1", "prod_10", "prod_5", "prod_6"], \
            f"Expected 4 Bay Area products, got {ids}"


# ── Faceted Search Tests ────────────────────────────────────────────────────

class TestFacetedSearch:

    def test_category_facet_counts(self):
        """Faceting on category must return 7 electronics and 3 accessories."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "*",
            "query_by": "title",
            "facet_by": "category"
        })
        data = resp.json()
        assert len(data.get("facet_counts", [])) > 0, \
            "No facet counts returned — category field may not be facetable"
        facet_counts = data["facet_counts"][0]["counts"]
        cat_map = {fc["value"]: fc["count"] for fc in facet_counts}
        assert cat_map.get("electronics") == 7, \
            f"Expected 7 electronics, got {cat_map.get('electronics')}"
        assert cat_map.get("accessories") == 3, \
            f"Expected 3 accessories, got {cat_map.get('accessories')}"

    def test_price_sort_ascending(self):
        """Top-3 cheapest products must be prod_7, prod_4, prod_9."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "*",
            "query_by": "title",
            "sort_by": "price:asc",
            "per_page": "3"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert ids == ["prod_7", "prod_4", "prod_9"], \
            f"Expected [prod_7, prod_4, prod_9], got {ids}"


# ── Multi-Way Synonym Tests ────────────────────────────────────────────────

class TestMultiWaySynonyms:

    def test_notebook_finds_laptop_products(self):
        """Searching 'notebook' must also find products with 'laptop' via multi-way synonym."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "notebook",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert "prod_1" in ids, \
            "prod_1 (laptop) not found when searching 'notebook' — synonym may be one-way"

    def test_portable_computer_finds_laptop_products(self):
        """Searching 'portable computer' must also find 'laptop' products."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "portable computer",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert "prod_1" in ids, \
            "prod_1 (laptop) not found when searching 'portable computer' — synonym may be one-way"


# ── One-Way Synonym Tests ──────────────────────────────────────────────────

class TestOneWaySynonyms:

    def test_mobile_finds_phone_products(self):
        """Searching 'mobile' must find phone/smartphone products via one-way expansion."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "mobile",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert "prod_10" in ids, \
            "prod_10 (Phone) not found when searching 'mobile' — one-way synonym not working"

    def test_phone_does_not_expand_to_mobile(self):
        """Searching 'phone' must NOT match mobile-only products (one-way, not multi-way)."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "mobile stand",
            "query_by": "title,description"
        })
        mobile_resp = resp.json()
        mobile_ids = [h["document"]["id"] for h in mobile_resp["hits"]]
        assert "prod_9" in mobile_ids, \
            "prod_9 not found for 'mobile stand' — data issue"

        resp = api_get("/collections/products/documents/search", params={
            "q": "phone",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert "prod_9" not in ids, \
            "prod_9 (mobile-only) found when searching 'phone' — synonym should be one-way from 'mobile', not multi-way"


# ── Curation Override Tests ─────────────────────────────────────────────────

class TestCuration:

    def test_exact_featured_pins_prod5(self):
        """Searching exactly 'featured' must pin prod_5 at position 1."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "featured",
            "query_by": "title,description"
        })
        data = resp.json()
        assert len(data["hits"]) > 0, "No results for 'featured'"
        assert data["hits"][0]["document"]["id"] == "prod_5", \
            "prod_5 not pinned at position 1 for exact 'featured' query"

    def test_exact_featured_excludes_prod4(self):
        """Searching exactly 'featured' must exclude prod_4."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "featured",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data["hits"]]
        assert "prod_4" not in ids, "prod_4 should be excluded from 'featured' results"

    def test_partial_featured_no_override(self):
        """Queries containing 'featured' but not exactly equal must NOT trigger the override."""
        resp = api_get("/collections/products/documents/search", params={
            "q": "featured deals",
            "query_by": "title,description"
        })
        data = resp.json()
        ids = [h["document"]["id"] for h in data.get("hits", [])]
        # prod_5 ("NovaCorp Portable Computer Elite") has zero organic relevance
        # to "featured deals". Its presence indicates the override triggered.
        assert "prod_5" not in ids, \
            "Curation override triggered on 'featured deals' — match rule should be exact, not contains"


# ── API Key Access Control Tests ────────────────────────────────────────────

class TestAPIKeyAccessControl:

    def test_search_key_file_exists_and_nonempty(self):
        assert os.path.exists("/app/search_only_key.txt"), \
            "/app/search_only_key.txt not found"
        with open("/app/search_only_key.txt") as f:
            key = f.read().strip()
        assert len(key) > 0, "Key file is empty"

    def test_search_key_can_search_products(self):
        with open("/app/search_only_key.txt") as f:
            key = f.read().strip()
        resp = requests.get(
            f"{BASE_URL}/collections/products/documents/search",
            params={"q": "*", "query_by": "title"},
            headers={"X-TYPESENSE-API-KEY": key})
        assert resp.status_code == 200, \
            f"Search-only key should be able to search products, got {resp.status_code}"

    def test_search_key_cannot_write(self):
        with open("/app/search_only_key.txt") as f:
            key = f.read().strip()
        resp = requests.post(
            f"{BASE_URL}/collections/products/documents",
            json={"id": "test_intruder", "title": "Should Fail", "price": 1.0},
            headers={"X-TYPESENSE-API-KEY": key})
        assert resp.status_code in [401, 403, 404], \
            f"Write should be forbidden but got {resp.status_code}"

    def test_search_key_cannot_access_brands(self):
        with open("/app/search_only_key.txt") as f:
            key = f.read().strip()
        resp = requests.get(
            f"{BASE_URL}/collections/brands/documents/search",
            params={"q": "*", "query_by": "name"},
            headers={"X-TYPESENSE-API-KEY": key})
        assert resp.status_code in [401, 403, 404], \
            f"Search on brands should be forbidden but got {resp.status_code}"
