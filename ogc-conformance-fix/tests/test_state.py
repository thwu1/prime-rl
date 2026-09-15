
"""OGC API - Features Part 1: Core conformance tests.

Tests verify that the server at http://localhost:5000 conforms to
OGC API - Features 1.0 requirements for landing page, collections,
feature retrieval, spatial/temporal filtering, query parameter validation,
content negotiation, pagination, and response metadata.
"""

import subprocess
import time
import requests
import pytest

SERVER_URL = "http://localhost:5000"


@pytest.fixture(scope="session", autouse=True)
def server():
    """Start the OGC API Features server for testing."""
    subprocess.run(["pkill", "-f", "python3 /app/server.py"],
                   capture_output=True)
    time.sleep(0.5)

    proc = subprocess.Popen(
        ["python3", "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    for _ in range(30):
        try:
            requests.get(f"{SERVER_URL}/", timeout=1)
            break
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.5)
    else:
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class TestLandingPage:
    """Tests for /req/core/root-op and /req/core/root-success."""

    def test_landing_page_returns_200(self):
        resp = requests.get(f"{SERVER_URL}/")
        assert resp.status_code == 200

    def test_landing_page_has_service_desc_link(self):
        """The landing page MUST contain a link with rel='service-desc' or
        rel='service-doc' (Requirement /req/core/root-success)."""
        resp = requests.get(f"{SERVER_URL}/")
        data = resp.json()
        rels = [link.get("rel") for link in data.get("links", [])]
        assert "service-desc" in rels or "service-doc" in rels, (
            f"Landing page must have a 'service-desc' or 'service-doc' link "
            f"relation. Found rels: {rels}"
        )

    def test_landing_page_has_conformance_link(self):
        """The landing page MUST contain a link with rel='conformance'
        (Requirement /req/core/root-success)."""
        resp = requests.get(f"{SERVER_URL}/")
        data = resp.json()
        rels = [link.get("rel") for link in data.get("links", [])]
        assert "conformance" in rels, (
            f"Landing page must have a 'conformance' link relation. "
            f"Found rels: {rels}"
        )

    def test_landing_page_has_data_link(self):
        """The landing page MUST contain a link with rel='data'."""
        resp = requests.get(f"{SERVER_URL}/")
        data = resp.json()
        rels = [link.get("rel") for link in data.get("links", [])]
        assert "data" in rels


class TestConformance:
    """Tests for /req/core/conformance-op and /req/core/conformance-success."""

    def test_conformance_returns_200(self):
        resp = requests.get(f"{SERVER_URL}/conformance")
        assert resp.status_code == 200

    def test_conformance_has_core_class(self):
        """conformsTo MUST include the Core conformance class URI."""
        resp = requests.get(f"{SERVER_URL}/conformance")
        data = resp.json()
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in data.get("conformsTo", [])


class TestCollections:
    """Tests for /req/core/fc-md-op, /req/core/fc-md-success, /req/core/crs84."""

    def test_collections_returns_200(self):
        resp = requests.get(f"{SERVER_URL}/collections")
        assert resp.status_code == 200

    def test_collections_has_collections_array(self):
        resp = requests.get(f"{SERVER_URL}/collections")
        data = resp.json()
        assert "collections" in data
        assert isinstance(data["collections"], list)
        assert len(data["collections"]) > 0

    def test_collections_default_crs_is_crs84(self):
        """If a collection reports a 'crs' property, the first value MUST be
        CRS84 or CRS84h (Requirement /req/core/crs84)."""
        resp = requests.get(f"{SERVER_URL}/collections")
        data = resp.json()
        for coll in data.get("collections", []):
            crs_list = coll.get("crs", [])
            if crs_list:
                assert crs_list[0] in (
                    "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                    "http://www.opengis.net/def/crs/OGC/0/CRS84h",
                ), (
                    f"Collection '{coll['id']}': first CRS must be CRS84 or "
                    f"CRS84h, got '{crs_list[0]}'"
                )


class TestFeaturesBbox:
    """Tests for /req/core/fc-bbox-definition and /req/core/fc-bbox-response.

    Bbox is specified as [minLon, minLat, maxLon, maxLat] in WGS 84.
    """

    def test_bbox_filter_includes_matching(self):
        """Features within bbox MUST be returned."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "bbox": "-130,40,-70,70",
            "limit": 100
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [f["properties"]["name"] for f in data["features"]]
        assert "Lake Superior" in names, (
            f"Lake Superior (lon ~-88, lat ~48) should be in bbox "
            f"[-130,40,-70,70]. Got: {names}"
        )
        assert "Great Bear Lake" in names, (
            f"Great Bear Lake (lon ~-121, lat ~66) should be in bbox "
            f"[-130,40,-70,70]. Got: {names}"
        )

    def test_bbox_filter_europe(self):
        """Bbox around Europe should include European lakes and exclude others."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "bbox": "5,44,35,62",
            "limit": 100
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [f["properties"]["name"] for f in data["features"]]
        assert "Lake Geneva" in names, (
            f"Lake Geneva (lon ~6.5, lat ~46.3) should be in bbox "
            f"[5,44,35,62]. Got: {names}"
        )
        assert "Lake Superior" not in names, (
            "Lake Superior should not be in European bbox"
        )
        assert "Lake Titicaca" not in names, (
            "Lake Titicaca should not be in European bbox"
        )


class TestFeaturesLimit:
    """Tests for /req/core/fc-limit-definition and /req/core/fc-limit-response."""

    def test_limit_respected(self):
        """Number of returned features MUST NOT exceed the limit."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items",
                            params={"limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["features"]) <= 3

    def test_invalid_limit_returns_400(self):
        """A non-integer limit value MUST result in HTTP 400
        (Requirement /req/core/query-param-invalid)."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items",
                            params={"limit": "unlimited"})
        assert resp.status_code == 400, (
            f"Expected 400 for limit='unlimited', got {resp.status_code}"
        )


class TestFeaturesDatetime:
    """Tests for /req/core/fc-time-definition and /req/core/fc-time-response.

    The datetime parameter supports open-ended ranges using '..' as a sentinel.
    """

    def test_datetime_open_start_range(self):
        """Open-start range '../{end}' MUST be supported."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "datetime": "../2020-01-01T00:00:00Z",
            "limit": 100
        })
        assert resp.status_code == 200, (
            f"Expected 200 for open-start datetime range, got {resp.status_code}"
        )
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    def test_datetime_open_end_range(self):
        """Open-end range '{start}/..' MUST be supported."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "datetime": "2024-01-01T00:00:00Z/..",
            "limit": 100
        })
        assert resp.status_code == 200, (
            f"Expected 200 for open-end datetime range, got {resp.status_code}"
        )
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    def test_datetime_open_start_filters_correctly(self):
        """Open-start range should only return features before the end date."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "datetime": "../2018-01-01T00:00:00Z",
            "limit": 100
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [f["properties"]["name"] for f in data["features"]]
        assert "Great Bear Lake" in names, (
            "Great Bear Lake (2016-08-22) should be in range ../2018-01-01"
        )
        assert "Lake Geneva" not in names, (
            "Lake Geneva (2023-07-12) should not be in range ../2018-01-01"
        )


class TestQueryParams:
    """Tests for /req/core/query-param-unknown."""

    def test_unknown_query_param_returns_400(self):
        """An unknown query parameter MUST result in HTTP 400
        (Requirement /req/core/query-param-unknown)."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items", params={
            "unknownQueryParameter98765": "value"
        })
        assert resp.status_code == 400, (
            f"Expected 400 for unknown query parameter, got {resp.status_code}"
        )


class TestFeaturesResponse:
    """Tests for /req/core/fc-response."""

    def test_number_returned_matches_actual_count(self):
        """numberReturned MUST equal the actual number of features in the
        response (not the total matching count)."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items",
                            params={"limit": 5})
        data = resp.json()
        actual_count = len(data["features"])
        reported_count = data.get("numberReturned")
        assert reported_count == actual_count, (
            f"numberReturned ({reported_count}) does not match actual feature "
            f"count ({actual_count})"
        )

    def test_number_matched_gte_returned(self):
        """numberMatched should be >= number of features in the response."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items",
                            params={"limit": 3})
        data = resp.json()
        assert data.get("numberMatched", 0) >= len(data["features"])

    def test_feature_collection_type(self):
        """Response MUST have type 'FeatureCollection'."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items")
        data = resp.json()
        assert data.get("type") == "FeatureCollection"

    def test_items_content_type_is_geojson(self):
        """Items endpoint MUST return Content-Type: application/geo+json
        per Requirement /req/core/fc-response."""
        resp = requests.get(f"{SERVER_URL}/collections/lakes/items")
        content_type = resp.headers.get("Content-Type", "")
        assert "application/geo+json" in content_type, (
            f"Items endpoint must return application/geo+json, "
            f"got '{content_type}'"
        )


class TestPagination:
    """Tests for pagination via next links."""

    def test_pagination_no_feature_gaps(self):
        """Following next links through all pages MUST collect every feature
        without skipping any (no off-by-one errors)."""
        resp_all = requests.get(f"{SERVER_URL}/collections/lakes/items",
                                params={"limit": 100})
        all_ids = set(f.get("id") for f in resp_all.json()["features"])

        paginated_ids = set()
        url = f"{SERVER_URL}/collections/lakes/items?limit=3"
        max_pages = 20

        for _ in range(max_pages):
            resp = requests.get(url)
            assert resp.status_code == 200
            data = resp.json()
            for f in data["features"]:
                paginated_ids.add(f.get("id"))

            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break

            if next_url is None:
                break
            url = next_url

        assert paginated_ids == all_ids, (
            f"Pagination missed features. Expected {len(all_ids)} IDs, "
            f"got {len(paginated_ids)}. "
            f"Missing: {all_ids - paginated_ids}"
        )

    def test_pagination_terminates(self):
        """Pagination must eventually terminate (no infinite loops)."""
        url = f"{SERVER_URL}/collections/lakes/items?limit=5"
        pages = 0
        max_pages = 50

        for _ in range(max_pages):
            resp = requests.get(url)
            assert resp.status_code == 200
            data = resp.json()
            pages += 1

            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break

            if next_url is None:
                break
            url = next_url

        assert pages < max_pages, "Pagination did not terminate"

    def test_pagination_preserves_bbox_filter(self):
        """Next links MUST preserve active bbox filter so that paginated
        traversal of filtered results remains consistent across pages."""
        # Africa bbox: minLon=-5, minLat=-20, maxLon=40, maxLat=20
        bbox = "-5,-20,40,20"
        resp_all = requests.get(f"{SERVER_URL}/collections/lakes/items",
                                params={"bbox": bbox, "limit": 100})
        assert resp_all.status_code == 200
        all_filtered = resp_all.json()["features"]
        expected_ids = set(f.get("id") for f in all_filtered)
        assert len(expected_ids) >= 3, (
            f"Expected at least 3 lakes in Africa bbox, got {len(expected_ids)}"
        )

        # Paginate through filtered results with small page size
        paginated_ids = set()
        url = f"{SERVER_URL}/collections/lakes/items?bbox={bbox}&limit=2"
        max_pages = 20

        for _ in range(max_pages):
            resp = requests.get(url)
            assert resp.status_code == 200
            data = resp.json()
            for feat in data["features"]:
                paginated_ids.add(feat.get("id"))

            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break
            if next_url is None:
                break
            url = next_url

        assert paginated_ids == expected_ids, (
            f"Filtered pagination failed. "
            f"Expected {len(expected_ids)} features, got {len(paginated_ids)}. "
            f"Missing: {expected_ids - paginated_ids}. "
            f"Extra: {paginated_ids - expected_ids}"
        )
