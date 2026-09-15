"""
OGC API Features Part 1: Core Conformance Tests

Verifies that the server at /app/ satisfies all Core and GeoJSON conformance
class requirements from the OGC API - Features 1.0 specification, covering
landing page, conformance declaration, API definition, collections, features,
bbox/limit/datetime filtering, error conditions, and pagination.
"""

import pytest
import requests
import json
import subprocess
import time
import os
import signal

BASE_URL = "http://localhost:5000"


@pytest.fixture(scope="session", autouse=True)
def server():
    """Start the server via /app/start.sh and wait for readiness."""
    start_script = "/app/start.sh"
    if not os.path.isfile(start_script):
        pytest.fail("/app/start.sh not found")

    os.chmod(start_script, 0o755)
    proc = subprocess.Popen(
        ["/bin/bash", start_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    for _ in range(30):
        try:
            r = requests.get(BASE_URL + "/", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        pytest.fail("Server did not become ready within 30 seconds")

    yield proc

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


# ---------------------------------------------------------------------------
# A.2.1  Landing Page  (Abstract Test 1)
# ---------------------------------------------------------------------------
class TestLandingPage:
    def test_landing_page_status(self):
        r = requests.get(f"{BASE_URL}/")
        assert r.status_code == 200

    def test_landing_page_content_type(self):
        r = requests.get(f"{BASE_URL}/", headers={"Accept": "application/json"})
        assert r.status_code == 200
        assert "application/json" in r.headers.get("Content-Type", "")

    def test_landing_page_has_links(self):
        data = requests.get(f"{BASE_URL}/").json()
        assert "links" in data
        assert isinstance(data["links"], list)
        assert len(data["links"]) > 0

    def test_landing_page_self_link(self):
        links = requests.get(f"{BASE_URL}/").json()["links"]
        assert any(l.get("rel") == "self" for l in links), "Missing 'self' link"

    def test_landing_page_service_desc_link(self):
        links = requests.get(f"{BASE_URL}/").json()["links"]
        assert any(l.get("rel") == "service-desc" for l in links), "Missing 'service-desc' link"

    def test_landing_page_conformance_link(self):
        links = requests.get(f"{BASE_URL}/").json()["links"]
        assert any(l.get("rel") == "conformance" for l in links), "Missing 'conformance' link"

    def test_landing_page_data_link(self):
        links = requests.get(f"{BASE_URL}/").json()["links"]
        assert any(l.get("rel") == "data" for l in links), "Missing 'data' link"

    def test_landing_page_service_desc_media_type(self):
        """OGC API Features 7.3: service-desc link type must reference OpenAPI."""
        links = requests.get(f"{BASE_URL}/").json()["links"]
        sd = [l for l in links if l.get("rel") == "service-desc"]
        assert len(sd) >= 1
        link_type = sd[0].get("type", "")
        assert "openapi" in link_type.lower(), \
            f"service-desc link type should reference OpenAPI media type, got '{link_type}'"


# ---------------------------------------------------------------------------
# A.2.2  Conformance  (Abstract Test 5)
# ---------------------------------------------------------------------------
class TestConformance:
    def test_conformance_status(self):
        assert requests.get(f"{BASE_URL}/conformance").status_code == 200

    def test_conformance_has_conforms_to(self):
        data = requests.get(f"{BASE_URL}/conformance").json()
        assert "conformsTo" in data
        assert isinstance(data["conformsTo"], list)

    def test_conformance_includes_core(self):
        ct = requests.get(f"{BASE_URL}/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in ct

    def test_conformance_includes_oas30(self):
        ct = requests.get(f"{BASE_URL}/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30" in ct

    def test_conformance_includes_geojson(self):
        ct = requests.get(f"{BASE_URL}/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson" in ct


# ---------------------------------------------------------------------------
# A.2.3  API Definition  (Abstract Test 3/4)
# ---------------------------------------------------------------------------
class TestApiDefinition:
    def _get_api_url(self):
        links = requests.get(f"{BASE_URL}/").json()["links"]
        sd = [l for l in links if l.get("rel") == "service-desc"]
        assert len(sd) >= 1
        href = sd[0]["href"]
        return BASE_URL + href if href.startswith("/") else href

    def test_api_definition_accessible(self):
        assert requests.get(self._get_api_url()).status_code == 200

    def test_api_definition_is_openapi3(self):
        doc = requests.get(self._get_api_url()).json()
        assert "openapi" in doc, "API definition must contain 'openapi' field"
        assert doc["openapi"].startswith("3."), f"Must be OpenAPI 3.x, got {doc['openapi']}"


# ---------------------------------------------------------------------------
# A.2.4  Feature Collections  (Abstract Test 9)
# ---------------------------------------------------------------------------
class TestCollections:
    def test_collections_status(self):
        assert requests.get(f"{BASE_URL}/collections").status_code == 200

    def test_collections_has_array(self):
        data = requests.get(f"{BASE_URL}/collections").json()
        assert "collections" in data
        assert isinstance(data["collections"], list)
        assert len(data["collections"]) >= 2

    def test_collections_required_properties(self):
        for c in requests.get(f"{BASE_URL}/collections").json()["collections"]:
            assert "id" in c, "Collection missing 'id'"
            assert "links" in c, f"Collection {c.get('id')} missing 'links'"

    def test_collections_items_link(self):
        for c in requests.get(f"{BASE_URL}/collections").json()["collections"]:
            assert any(l.get("rel") == "items" for l in c["links"]), \
                f"Collection {c['id']} missing 'items' link"

    def test_collection_ids(self):
        ids = [c["id"] for c in requests.get(f"{BASE_URL}/collections").json()["collections"]]
        assert "weather_stations" in ids
        assert "seismic_events" in ids

    def test_collections_have_extent(self):
        for c in requests.get(f"{BASE_URL}/collections").json()["collections"]:
            assert "extent" in c, f"Collection {c['id']} missing 'extent'"
            assert "spatial" in c["extent"]
            assert "bbox" in c["extent"]["spatial"]

    def test_extent_bbox_crs84_axis_order(self):
        """CRS84 bbox must be [minLon, minLat, maxLon, maxLat]."""
        bbox = requests.get(
            f"{BASE_URL}/collections/weather_stations"
        ).json()["extent"]["spatial"]["bbox"][0]
        # Weather stations span from lon -149.9 (Anchorage) to 174.8 (Auckland)
        # and from lat -36.8 (Auckland) to 64.1 (Reykjavik).
        # bbox[0] = minLon must be < -100; bbox[2] = maxLon must be > 100.
        assert bbox[0] < -100, \
            f"bbox[0] (minLon) should be < -100 for CRS84 axis order, got {bbox[0]}"
        assert bbox[2] > 100, \
            f"bbox[2] (maxLon) should be > 100 for CRS84 axis order, got {bbox[2]}"

    def test_extent_bbox_valid_coordinates(self):
        """Extent bbox latitude values must be within [-90, 90] per CRS84."""
        bbox = requests.get(
            f"{BASE_URL}/collections/weather_stations"
        ).json()["extent"]["spatial"]["bbox"][0]
        assert -180 <= bbox[0] <= 180, \
            f"bbox[0] (minLon) out of valid range [-180,180], got {bbox[0]}"
        assert -90 <= bbox[1] <= 90, \
            f"bbox[1] (minLat) out of valid range [-90,90], got {bbox[1]}"
        assert -180 <= bbox[2] <= 180, \
            f"bbox[2] (maxLon) out of valid range [-180,180], got {bbox[2]}"
        assert -90 <= bbox[3] <= 90, \
            f"bbox[3] (maxLat) out of valid range [-90,90], got {bbox[3]} — possible coordinate swap in source data"

    def test_extent_bbox_seismic_valid(self):
        """Seismic events extent must also have valid CRS84 coordinates."""
        bbox = requests.get(
            f"{BASE_URL}/collections/seismic_events"
        ).json()["extent"]["spatial"]["bbox"][0]
        assert -90 <= bbox[1] <= 90, \
            f"seismic bbox[1] (minLat) out of range, got {bbox[1]}"
        assert -90 <= bbox[3] <= 90, \
            f"seismic bbox[3] (maxLat) out of range, got {bbox[3]}"


# ---------------------------------------------------------------------------
# A.2.5  Single Collection
# ---------------------------------------------------------------------------
class TestSingleCollection:
    def test_status(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations").status_code == 200

    def test_id(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations").json()["id"] == "weather_stations"

    def test_links(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations").json()
        assert any(l.get("rel") == "items" for l in data["links"])

    def test_extent_bbox(self):
        ext = requests.get(f"{BASE_URL}/collections/weather_stations").json()["extent"]
        bbox = ext["spatial"]["bbox"]
        assert isinstance(bbox, list) and len(bbox) >= 1 and len(bbox[0]) >= 4

    def test_nonexistent_404(self):
        assert requests.get(f"{BASE_URL}/collections/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# A.2.6  Features  (Abstract Test 13/14/15)
# ---------------------------------------------------------------------------
class TestFeatures:
    def test_status(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items").status_code == 200

    def test_content_type(self):
        r = requests.get(f"{BASE_URL}/collections/weather_stations/items",
                         headers={"Accept": "application/geo+json"})
        ct = r.headers.get("Content-Type", "")
        assert "geo+json" in ct or "application/json" in ct

    def test_type_property(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items").json()["type"] == "FeatureCollection"

    def test_features_array(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items").json()
        assert isinstance(data["features"], list) and len(data["features"]) > 0

    def test_feature_structure(self):
        for f in requests.get(f"{BASE_URL}/collections/weather_stations/items").json()["features"]:
            assert f["type"] == "Feature"
            assert "id" in f
            assert "geometry" in f
            assert "properties" in f

    def test_geometry_crs84(self):
        """All feature coordinates must be valid CRS84 [lon, lat]."""
        for f in requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=100").json()["features"]:
            if f["geometry"] and f["geometry"]["type"] == "Point":
                lon, lat = f["geometry"]["coordinates"][:2]
                assert -180 <= lon <= 180, \
                    f"Feature {f['id']} lon={lon} out of range — possible lat/lon swap in data"
                assert -90 <= lat <= 90, \
                    f"Feature {f['id']} lat={lat} out of range — possible lat/lon swap in data"

    def test_has_links(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items").json()
        assert "links" in data
        assert any(l.get("rel") == "self" for l in data["links"])

    def test_number_returned(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items").json()
        assert "numberReturned" in data
        assert data["numberReturned"] == len(data["features"])

    def test_number_matched(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items").json()
        assert "numberMatched" in data
        assert data["numberMatched"] >= data["numberReturned"]

    def test_total_weather_stations(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=100").json()
        assert data["numberMatched"] == 15

    def test_total_seismic_events(self):
        data = requests.get(f"{BASE_URL}/collections/seismic_events/items?limit=100").json()
        assert data["numberMatched"] == 12

    def test_all_feature_coordinates_valid(self):
        """Every feature across all collections must have valid CRS84 coordinates."""
        for coll in ["weather_stations", "seismic_events"]:
            feats = requests.get(f"{BASE_URL}/collections/{coll}/items?limit=100").json()["features"]
            for f in feats:
                if f["geometry"] and f["geometry"]["type"] == "Point":
                    lon, lat = f["geometry"]["coordinates"][:2]
                    assert -180 <= lon <= 180 and -90 <= lat <= 90, \
                        f"{coll}/{f['id']} has invalid CRS84 coordinates [{lon},{lat}]"


# ---------------------------------------------------------------------------
# Single Feature
# ---------------------------------------------------------------------------
class TestSingleFeature:
    def test_status(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").status_code == 200

    def test_type(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").json()["type"] == "Feature"

    def test_id(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").json()["id"] == "ws-001"

    def test_geometry(self):
        g = requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").json()["geometry"]
        assert g["type"] == "Point"
        assert abs(g["coordinates"][0] - (-73.9857)) < 0.001
        assert abs(g["coordinates"][1] - 40.7484) < 0.001

    def test_properties(self):
        p = requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").json()["properties"]
        assert p["name"] == "NYC Central Park"

    def test_has_links(self):
        assert "links" in requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-001").json()

    def test_seismic_feature(self):
        data = requests.get(f"{BASE_URL}/collections/seismic_events/items/eq-001").json()
        assert data["id"] == "eq-001"
        assert data["properties"]["magnitude"] == 5.2

    def test_nonexistent_404(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-999").status_code == 404

    def test_tokyo_coordinates(self):
        """ws-003 (Tokyo Haneda) must have valid CRS84 coordinates for Tokyo region."""
        g = requests.get(f"{BASE_URL}/collections/weather_stations/items/ws-003").json()["geometry"]
        lon, lat = g["coordinates"][:2]
        assert 130 < lon < 150, \
            f"Tokyo lon should be ~139.7, got {lon} — GeoJSON coordinates must be [lon,lat]"
        assert 30 < lat < 40, \
            f"Tokyo lat should be ~35.7, got {lat} — GeoJSON coordinates must be [lon,lat]"


# ---------------------------------------------------------------------------
# A.2.6  BBox Filtering  (Abstract Test 17)
# ---------------------------------------------------------------------------
class TestBBoxFiltering:
    def test_bbox_nyc(self):
        """BBox tightly around NYC should return only ws-001."""
        r = requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=-75,40,-72,42")
        assert r.status_code == 200
        ids = [f["id"] for f in r.json()["features"]]
        assert ids == ["ws-001"], f"Expected only ws-001, got {ids}"

    def test_bbox_europe(self):
        """BBox over Europe: London, Cairo, Moscow, Reykjavik."""
        ids = {f["id"] for f in
               requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=-25,28,45,66").json()["features"]}
        assert ids == {"ws-002", "ws-007", "ws-008", "ws-012"}, f"Got {ids}"

    def test_bbox_southern_hemisphere(self):
        """South of equator: Sydney, Sao Paulo, Cape Town, Auckland, Buenos Aires."""
        ids = {f["id"] for f in
               requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=-180,-90,180,0").json()["features"]}
        assert ids == {"ws-004", "ws-005", "ws-010", "ws-011", "ws-014"}, f"Got {ids}"

    def test_all_within_bbox(self):
        """Every returned feature must have geometry inside the bbox."""
        w, s, e, n = -80, 30, -70, 45
        for f in requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox={w},{s},{e},{n}").json()["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            assert w <= lon <= e and s <= lat <= n, f"{f['id']} at ({lon},{lat}) outside bbox"

    def test_bbox_seismic_pacific(self):
        ids = {f["id"] for f in
               requests.get(f"{BASE_URL}/collections/seismic_events/items?bbox=130,30,180,45").json()["features"]}
        assert "eq-001" in ids

    def test_bbox_empty_result(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=0,0,1,1").json()
        assert len(data["features"]) == 0
        assert data["numberMatched"] == 0
        assert data["numberReturned"] == 0

    def test_bbox_number_matched(self):
        """numberMatched must reflect filtered count, not total collection size."""
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=-75,40,-72,42").json()
        assert data["numberMatched"] == 1, \
            f"Expected numberMatched=1 for NYC bbox, got {data['numberMatched']}"

    def test_bbox_invalid_returns_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=invalid").status_code == 400

    def test_bbox_wrong_count_returns_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=1,2,3").status_code == 400

    def test_bbox_japan(self):
        """BBox around Japan must include ws-003 (Tokyo Haneda)."""
        ids = {f["id"] for f in
               requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=135,33,145,38").json()["features"]}
        assert "ws-003" in ids, \
            f"Expected ws-003 (Tokyo) in Japan bbox [135,33,145,38], got {ids}"


# ---------------------------------------------------------------------------
# A.2.6  Limit Parameter  (Abstract Test 16)
# ---------------------------------------------------------------------------
class TestLimitParameter:
    def test_limit_3(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=3").json()
        assert len(data["features"]) <= 3
        assert data["numberReturned"] <= 3

    def test_limit_1(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=1").json()
        assert len(data["features"]) == 1

    def test_limit_preserves_number_matched(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=3").json()
        assert data["numberMatched"] == 15

    def test_limit_invalid_returns_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=unlimited").status_code == 400

    def test_limit_negative_returns_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=-5").status_code == 400

    def test_limit_zero_returns_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=0").status_code == 400


# ---------------------------------------------------------------------------
# A.2.6  Datetime Filtering  (Abstract Test 18)
# ---------------------------------------------------------------------------
class TestDatetimeFiltering:
    def test_instant(self):
        ids = {f["id"] for f in
               requests.get(f"{BASE_URL}/collections/weather_stations/items?datetime=2024-03-15T12:00:00Z").json()["features"]}
        assert "ws-001" in ids

    def test_range(self):
        ids = {f["id"] for f in requests.get(
            f"{BASE_URL}/collections/weather_stations/items?datetime=2024-03-15T07:00:00Z/2024-03-15T12:00:00Z"
        ).json()["features"]}
        assert ids == {"ws-001", "ws-005", "ws-009", "ws-012", "ws-014", "ws-015"}, f"Got {ids}"

    def test_open_start(self):
        r = requests.get(
            f"{BASE_URL}/collections/seismic_events/items?datetime=../2024-02-03T08:11:45Z"
        )
        assert r.status_code == 200, f"Expected 200 for open-start interval, got {r.status_code}"
        ids = {f["id"] for f in r.json()["features"]}
        assert ids == {"eq-001", "eq-002", "eq-003"}, f"Got {ids}"

    def test_open_end(self):
        r = requests.get(
            f"{BASE_URL}/collections/seismic_events/items?datetime=2024-05-01T00:00:00Z/.."
        )
        assert r.status_code == 200, f"Expected 200 for open-end interval, got {r.status_code}"
        ids = {f["id"] for f in r.json()["features"]}
        assert ids == {"eq-010", "eq-011", "eq-012"}, f"Got {ids}"

    def test_seismic_range(self):
        ids = {f["id"] for f in requests.get(
            f"{BASE_URL}/collections/seismic_events/items?datetime=2024-03-01T00:00:00Z/2024-03-31T23:59:59Z"
        ).json()["features"]}
        assert ids == {"eq-005", "eq-006", "eq-007"}, f"Got {ids}"

    def test_no_match(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?datetime=2020-01-01T00:00:00Z").json()
        assert len(data["features"]) == 0


# ---------------------------------------------------------------------------
# A.2.7  Error Conditions  (Abstract Test 20/21)
# ---------------------------------------------------------------------------
class TestErrorConditions:
    def test_unknown_param_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?unknownParam=1").status_code == 400

    def test_invalid_limit_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=unlimited").status_code == 400

    def test_invalid_bbox_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=invalid").status_code == 400

    def test_bbox_three_coords_400(self):
        assert requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=1,2,3").status_code == 400


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class TestPagination:
    def test_next_link_present(self):
        links = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=5").json()["links"]
        assert any(l.get("rel") == "next" for l in links), "Must have 'next' link when more features available"

    def test_no_next_when_complete(self):
        links = requests.get(f"{BASE_URL}/collections/weather_stations/items?limit=100").json()["links"]
        assert not any(l.get("rel") == "next" for l in links)

    def test_follow_next_yields_all(self):
        all_ids = set()
        url = f"{BASE_URL}/collections/weather_stations/items?limit=5"
        for _ in range(10):
            data = requests.get(url).json()
            for f in data["features"]:
                all_ids.add(f["id"])
            nxt = [l for l in data.get("links", []) if l.get("rel") == "next"]
            if not nxt:
                break
            url = nxt[0]["href"]
            if url.startswith("/"):
                url = BASE_URL + url
        assert len(all_ids) == 15, f"Pagination should yield all 15 stations, got {len(all_ids)}: {all_ids}"

    def test_no_duplicates(self):
        all_ids = []
        url = f"{BASE_URL}/collections/weather_stations/items?limit=3"
        for _ in range(10):
            data = requests.get(url).json()
            all_ids.extend(f["id"] for f in data["features"])
            nxt = [l for l in data.get("links", []) if l.get("rel") == "next"]
            if not nxt:
                break
            url = nxt[0]["href"]
            if url.startswith("/"):
                url = BASE_URL + url
        assert len(all_ids) == len(set(all_ids)), f"Duplicates found: {all_ids}"

    def test_paginated_bbox_preserves_filter(self):
        """Pagination next link must preserve the bbox query parameter."""
        data = requests.get(
            f"{BASE_URL}/collections/weather_stations/items?bbox=-180,-90,180,90&limit=5"
        ).json()
        nxt = [l for l in data.get("links", []) if l.get("rel") == "next"]
        assert len(nxt) > 0, "Expected next link for paginated bbox query"
        next_url = nxt[0]["href"]
        assert "bbox=" in next_url, \
            f"Next link must preserve bbox query parameter: {next_url}"

    def test_paginated_datetime_preserves_filter(self):
        """Pagination next link must preserve the datetime query parameter."""
        data = requests.get(
            f"{BASE_URL}/collections/weather_stations/items"
            f"?datetime=2024-03-15T07:00:00Z/2024-03-15T18:00:00Z&limit=3"
        ).json()
        nxt = [l for l in data.get("links", []) if l.get("rel") == "next"]
        assert len(nxt) > 0, "Expected next link for paginated datetime query"
        next_url = nxt[0]["href"]
        assert "datetime=" in next_url, \
            f"Next link must preserve datetime query parameter: {next_url}"


# ---------------------------------------------------------------------------
# Combined Filters
# ---------------------------------------------------------------------------
class TestCombinedFilters:
    def test_bbox_and_limit(self):
        data = requests.get(f"{BASE_URL}/collections/weather_stations/items?bbox=-180,-90,180,90&limit=3").json()
        assert len(data["features"]) <= 3
        assert data["numberMatched"] == 15

    def test_bbox_and_datetime(self):
        """Western+Northern hemisphere on 2024-03-15: NYC, London, LA, Reykjavik, Anchorage."""
        ids = {f["id"] for f in requests.get(
            f"{BASE_URL}/collections/weather_stations/items"
            f"?bbox=-180,0,0,90&datetime=2024-03-15T00:00:00Z/2024-03-15T23:59:59Z"
        ).json()["features"]}
        assert ids == {"ws-001", "ws-002", "ws-009", "ws-012", "ws-015"}, f"Got {ids}"
