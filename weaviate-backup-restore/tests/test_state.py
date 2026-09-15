#!/usr/bin/env python3
"""
Verification tests for Weaviate cross-instance replication.

Validates that the secondary instance (port 8079) faithfully reproduces
the primary's (port 8080) complete state: schema, index configuration,
tenants, object data, UUIDs, and vectors.
"""


import pytest
import requests

PRIMARY_URL = "http://localhost:8080"
SECONDARY_URL = "http://localhost:8079"
TIMEOUT = 15

EXPECTED_COLLECTIONS = {"Products", "Reviews"}

EXPECTED_COUNTS = {
    "Products": {"store_us": 12, "store_eu": 10, "store_asia": 8},
    "Reviews": {"store_us": 18, "store_eu": 15, "store_asia": 12},
}

EXPECTED_BM25 = {
    "Products": {"b": 0.75, "k1": 1.2},
    "Reviews": {"b": 0.5, "k1": 1.5},
}

EXPECTED_HNSW = {
    "Products": {
        "distance": "cosine",
        "efConstruction": 256,
        "maxConnections": 32,
        "ef": 128,
    },
    "Reviews": {
        "distance": "cosine",
        "efConstruction": 128,
        "maxConnections": 16,
        "ef": 64,
    },
}

EXPECTED_PROPERTIES = {
    "Products": {"name", "description", "category", "price", "in_stock", "sku"},
    "Reviews": {"content", "rating", "author", "verified_purchase"},
}

EXPECTED_TENANTS = {"store_us", "store_eu", "store_asia"}

# Property-level index settings to verify on the secondary
EXPECTED_PROPERTY_INDEX = {
    "Products": {
        "name": {"tokenization": "word", "indexFilterable": True, "indexSearchable": True},
        "description": {"tokenization": "word", "indexFilterable": False, "indexSearchable": True},
        "category": {"tokenization": "field", "indexFilterable": True, "indexSearchable": False},
        "price": {"indexFilterable": True, "indexRangeFilters": True},
        "in_stock": {"indexFilterable": True},
        "sku": {"tokenization": "field", "indexFilterable": True, "indexSearchable": False},
    },
    "Reviews": {
        "content": {"tokenization": "word", "indexFilterable": False, "indexSearchable": True},
        "rating": {"indexFilterable": True, "indexRangeFilters": True},
        "author": {"tokenization": "field", "indexFilterable": True, "indexSearchable": False},
        "verified_purchase": {"indexFilterable": True},
    },
}


# ---------------------------------------------------------------------------
# Readiness — both instances
# ---------------------------------------------------------------------------


class TestInstanceReady:
    def test_primary_accessible(self):
        """Primary Weaviate instance is running and responding."""
        resp = requests.get(f"{PRIMARY_URL}/v1/.well-known/ready", timeout=TIMEOUT)
        assert resp.status_code == 200

    def test_secondary_accessible(self):
        """Secondary Weaviate instance is running and responding."""
        resp = requests.get(f"{SECONDARY_URL}/v1/.well-known/ready", timeout=TIMEOUT)
        assert resp.status_code == 200

    def test_schema_endpoint(self):
        """Schema endpoint on secondary returns valid JSON with classes."""
        resp = requests.get(f"{SECONDARY_URL}/v1/schema", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        assert "classes" in data


# ---------------------------------------------------------------------------
# Schema structure
# ---------------------------------------------------------------------------


class TestSchemaStructure:
    def test_both_collections_exist(self):
        """Both Products and Reviews collections exist on secondary."""
        resp = requests.get(f"{SECONDARY_URL}/v1/schema", timeout=TIMEOUT)
        assert resp.status_code == 200
        classes = {c["class"] for c in resp.json()["classes"]}
        assert EXPECTED_COLLECTIONS.issubset(classes), (
            f"Missing collections: {EXPECTED_COLLECTIONS - classes}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_properties_present(self, collection):
        """All expected properties exist on the collection."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        actual_props = {p["name"] for p in resp.json()["properties"]}
        expected = EXPECTED_PROPERTIES[collection]
        assert expected.issubset(actual_props), (
            f"Missing properties in {collection}: {expected - actual_props}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_multi_tenancy_enabled(self, collection):
        """Multi-tenancy is enabled on the collection."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        mt = resp.json().get("multiTenancyConfig", {})
        assert mt.get("enabled") is True, "Multi-tenancy not enabled"

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_vectorizer_none(self, collection):
        """Vectorizer is set to 'none'."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        vectorizer = resp.json().get("vectorizer", "")
        assert vectorizer == "none", f"Expected vectorizer 'none', got '{vectorizer}'"


# ---------------------------------------------------------------------------
# BM25 configuration
# ---------------------------------------------------------------------------


class TestBM25Config:
    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_bm25_b(self, collection):
        """BM25 b parameter matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        bm25 = resp.json()["invertedIndexConfig"]["bm25"]
        expected_b = EXPECTED_BM25[collection]["b"]
        assert abs(bm25["b"] - expected_b) < 0.01, (
            f"BM25 b: expected {expected_b}, got {bm25['b']}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_bm25_k1(self, collection):
        """BM25 k1 parameter matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        bm25 = resp.json()["invertedIndexConfig"]["bm25"]
        expected_k1 = EXPECTED_BM25[collection]["k1"]
        assert abs(bm25["k1"] - expected_k1) < 0.01, (
            f"BM25 k1: expected {expected_k1}, got {bm25['k1']}"
        )


# ---------------------------------------------------------------------------
# HNSW vector index configuration
# ---------------------------------------------------------------------------


class TestHNSWConfig:
    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_hnsw_distance(self, collection):
        """HNSW distance metric matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        vic = resp.json()["vectorIndexConfig"]
        expected = EXPECTED_HNSW[collection]["distance"]
        assert vic["distance"] == expected, (
            f"HNSW distance: expected '{expected}', got '{vic.get('distance')}'"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_hnsw_ef_construction(self, collection):
        """HNSW efConstruction matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        vic = resp.json()["vectorIndexConfig"]
        expected = EXPECTED_HNSW[collection]["efConstruction"]
        assert vic["efConstruction"] == expected, (
            f"HNSW efConstruction: expected {expected}, got {vic.get('efConstruction')}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_hnsw_max_connections(self, collection):
        """HNSW maxConnections matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        vic = resp.json()["vectorIndexConfig"]
        expected = EXPECTED_HNSW[collection]["maxConnections"]
        assert vic["maxConnections"] == expected, (
            f"HNSW maxConnections: expected {expected}, got {vic.get('maxConnections')}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_hnsw_ef(self, collection):
        """HNSW ef (query-time) matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        vic = resp.json()["vectorIndexConfig"]
        expected = EXPECTED_HNSW[collection]["ef"]
        assert vic["ef"] == expected, (
            f"HNSW ef: expected {expected}, got {vic.get('ef')}"
        )


# ---------------------------------------------------------------------------
# Property-level index settings
# ---------------------------------------------------------------------------


class TestPropertyIndexConfig:
    @pytest.mark.parametrize(
        "collection,prop_name",
        [
            ("Products", "name"),
            ("Products", "description"),
            ("Products", "category"),
            ("Products", "sku"),
            ("Reviews", "content"),
            ("Reviews", "author"),
        ],
    )
    def test_tokenization(self, collection, prop_name):
        """Property tokenization setting matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        props = {p["name"]: p for p in resp.json()["properties"]}
        assert prop_name in props, f"Property {prop_name} not found"
        expected = EXPECTED_PROPERTY_INDEX[collection][prop_name]["tokenization"]
        actual = props[prop_name].get("tokenization")
        assert actual == expected, (
            f"{collection}.{prop_name} tokenization: expected '{expected}', got '{actual}'"
        )

    @pytest.mark.parametrize(
        "collection,prop_name",
        [
            ("Products", "name"),
            ("Products", "description"),
            ("Products", "category"),
            ("Products", "price"),
            ("Products", "in_stock"),
            ("Reviews", "content"),
            ("Reviews", "rating"),
            ("Reviews", "author"),
            ("Reviews", "verified_purchase"),
        ],
    )
    def test_index_filterable(self, collection, prop_name):
        """Property indexFilterable setting matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        props = {p["name"]: p for p in resp.json()["properties"]}
        assert prop_name in props, f"Property {prop_name} not found"
        expected = EXPECTED_PROPERTY_INDEX[collection][prop_name].get("indexFilterable")
        if expected is not None:
            actual = props[prop_name].get("indexFilterable")
            assert actual == expected, (
                f"{collection}.{prop_name} indexFilterable: expected {expected}, got {actual}"
            )

    @pytest.mark.parametrize(
        "collection,prop_name",
        [
            ("Products", "name"),
            ("Products", "description"),
            ("Products", "category"),
            ("Reviews", "content"),
            ("Reviews", "author"),
        ],
    )
    def test_index_searchable(self, collection, prop_name):
        """Property indexSearchable setting matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        props = {p["name"]: p for p in resp.json()["properties"]}
        assert prop_name in props, f"Property {prop_name} not found"
        expected = EXPECTED_PROPERTY_INDEX[collection][prop_name].get("indexSearchable")
        if expected is not None:
            actual = props[prop_name].get("indexSearchable")
            assert actual == expected, (
                f"{collection}.{prop_name} indexSearchable: expected {expected}, got {actual}"
            )

    @pytest.mark.parametrize(
        "collection,prop_name",
        [("Products", "price"), ("Reviews", "rating")],
    )
    def test_index_range_filters(self, collection, prop_name):
        """Property indexRangeFilters setting matches specification."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        props = {p["name"]: p for p in resp.json()["properties"]}
        assert prop_name in props, f"Property {prop_name} not found"
        expected = EXPECTED_PROPERTY_INDEX[collection][prop_name].get("indexRangeFilters")
        if expected is not None:
            actual = props[prop_name].get("indexRangeFilters")
            assert actual == expected, (
                f"{collection}.{prop_name} indexRangeFilters: expected {expected}, got {actual}"
            )


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


class TestTenants:
    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_tenants_exist(self, collection):
        """All expected tenants exist on the collection."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}/tenants", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        tenant_names = {t["name"] for t in resp.json()}
        assert EXPECTED_TENANTS.issubset(tenant_names), (
            f"Missing tenants in {collection}: {EXPECTED_TENANTS - tenant_names}"
        )

    @pytest.mark.parametrize("collection", ["Products", "Reviews"])
    def test_tenants_active(self, collection):
        """All tenants are in an active state (HOT or ACTIVE)."""
        resp = requests.get(
            f"{SECONDARY_URL}/v1/schema/{collection}/tenants", timeout=TIMEOUT
        )
        assert resp.status_code == 200
        for tenant in resp.json():
            if tenant["name"] in EXPECTED_TENANTS:
                status = tenant.get("activityStatus", "UNKNOWN")
                assert status in ("HOT", "ACTIVE"), (
                    f"Tenant {tenant['name']} in {collection} has status "
                    f"'{status}', expected HOT or ACTIVE"
                )


# ---------------------------------------------------------------------------
# Object counts
# ---------------------------------------------------------------------------


class TestObjectCounts:
    @pytest.mark.parametrize(
        "collection,tenant,expected_count",
        [
            ("Products", "store_us", 12),
            ("Products", "store_eu", 10),
            ("Products", "store_asia", 8),
            ("Reviews", "store_us", 18),
            ("Reviews", "store_eu", 15),
            ("Reviews", "store_asia", 12),
        ],
    )
    def test_object_count(self, collection, tenant, expected_count):
        """Per-tenant object count matches expected value."""
        query = {
            "query": (
                "{ Aggregate { "
                + collection
                + '(tenant: "'
                + tenant
                + '") { meta { count } } } }'
            )
        }
        resp = requests.post(
            f"{SECONDARY_URL}/v1/graphql", json=query, timeout=30
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"
        count = data["data"]["Aggregate"][collection][0]["meta"]["count"]
        assert count == expected_count, (
            f"{collection}/{tenant}: expected {expected_count}, got {count}"
        )


# ---------------------------------------------------------------------------
# Data integrity — vectors present
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    def test_products_have_vectors(self):
        """Products on the secondary instance have 128-dim vectors."""
        query = {
            "query": (
                '{ Get { Products(tenant: "store_us", limit: 1) '
                "{ name _additional { vector } } } }"
            )
        }
        resp = requests.post(
            f"{SECONDARY_URL}/v1/graphql", json=query, timeout=30
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"
        objects = data["data"]["Get"]["Products"]
        assert len(objects) > 0, "No products returned from secondary instance"
        vector = objects[0]["_additional"]["vector"]
        assert len(vector) == 128, (
            f"Expected 128-dim vector, got {len(vector)}-dim"
        )

    def test_reviews_have_vectors(self):
        """Reviews on the secondary instance have 128-dim vectors."""
        query = {
            "query": (
                '{ Get { Reviews(tenant: "store_us", limit: 1) '
                "{ content _additional { vector } } } }"
            )
        }
        resp = requests.post(
            f"{SECONDARY_URL}/v1/graphql", json=query, timeout=30
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"
        objects = data["data"]["Get"]["Reviews"]
        assert len(objects) > 0, "No reviews returned from secondary instance"
        vector = objects[0]["_additional"]["vector"]
        assert len(vector) == 128, (
            f"Expected 128-dim vector, got {len(vector)}-dim"
        )


# ---------------------------------------------------------------------------
# Cross-instance fidelity — UUIDs and vector data match
# ---------------------------------------------------------------------------


def _get_objects_rest(url, class_name, tenant, limit=100):
    """Fetch objects from a Weaviate instance via REST API with vectors."""
    resp = requests.get(
        f"{url}/v1/objects",
        params={
            "class": class_name,
            "tenant": tenant,
            "include": "vector",
            "limit": limit,
        },
        timeout=30,
    )
    assert resp.status_code == 200, (
        f"Failed to fetch objects from {url}: {resp.status_code} {resp.text}"
    )
    return resp.json().get("objects", [])


class TestCrossInstanceFidelity:
    def test_product_uuids_match(self):
        """Product UUIDs on secondary match primary for store_us."""
        primary_objs = _get_objects_rest(PRIMARY_URL, "Products", "store_us")
        secondary_objs = _get_objects_rest(SECONDARY_URL, "Products", "store_us")
        primary_ids = {o["id"] for o in primary_objs}
        secondary_ids = {o["id"] for o in secondary_objs}
        assert primary_ids == secondary_ids, (
            f"UUID mismatch. Only in primary: {primary_ids - secondary_ids}. "
            f"Only in secondary: {secondary_ids - primary_ids}"
        )

    def test_review_uuids_match(self):
        """Review UUIDs on secondary match primary for store_eu."""
        primary_objs = _get_objects_rest(PRIMARY_URL, "Reviews", "store_eu")
        secondary_objs = _get_objects_rest(SECONDARY_URL, "Reviews", "store_eu")
        primary_ids = {o["id"] for o in primary_objs}
        secondary_ids = {o["id"] for o in secondary_objs}
        assert primary_ids == secondary_ids, (
            f"UUID mismatch. Only in primary: {primary_ids - secondary_ids}. "
            f"Only in secondary: {secondary_ids - primary_ids}"
        )

    def test_vector_values_match(self):
        """Vector values on secondary are numerically identical to primary."""
        primary_objs = _get_objects_rest(PRIMARY_URL, "Products", "store_us")
        secondary_objs = _get_objects_rest(SECONDARY_URL, "Products", "store_us")
        assert len(primary_objs) > 0, "No products on primary"
        assert len(secondary_objs) > 0, "No products on secondary"

        # Build lookup by UUID
        secondary_by_id = {o["id"]: o for o in secondary_objs}

        # Check each primary object's vector matches on secondary
        for pobj in primary_objs:
            uid = pobj["id"]
            assert uid in secondary_by_id, f"Object {uid} missing on secondary"
            sobj = secondary_by_id[uid]
            pvec = pobj.get("vector", [])
            svec = sobj.get("vector", [])
            assert len(pvec) == len(svec) == 128, (
                f"Vector dimension mismatch for {uid}: "
                f"primary={len(pvec)}, secondary={len(svec)}"
            )
            for dim_i, (pv, sv) in enumerate(zip(pvec, svec)):
                assert abs(pv - sv) < 1e-5, (
                    f"Vector value mismatch for {uid} at dim {dim_i}: "
                    f"primary={pv}, secondary={sv}"
                )

    def test_properties_data_match(self):
        """Object property values on secondary match primary."""
        primary_objs = _get_objects_rest(PRIMARY_URL, "Reviews", "store_asia")
        secondary_objs = _get_objects_rest(SECONDARY_URL, "Reviews", "store_asia")
        secondary_by_id = {o["id"]: o for o in secondary_objs}

        for pobj in primary_objs:
            uid = pobj["id"]
            assert uid in secondary_by_id, f"Object {uid} missing on secondary"
            sobj = secondary_by_id[uid]
            for key in ("content", "author", "rating", "verified_purchase"):
                assert pobj["properties"].get(key) == sobj["properties"].get(key), (
                    f"Property '{key}' mismatch for {uid}: "
                    f"primary={pobj['properties'].get(key)!r}, "
                    f"secondary={sobj['properties'].get(key)!r}"
                )
