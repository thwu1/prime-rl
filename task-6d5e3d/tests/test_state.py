
"""
Verification tests for the OGC API - Features endpoint.
Tests collection discovery, feature querying, spatial/temporal/property
filtering, CRS support, and transactional operations.
"""

import pytest
import requests
import time

BASE_URL = "http://localhost:5000"
TIMEOUT = 15


@pytest.fixture(autouse=True, scope="session")
def wait_for_server():
    """Wait for the pygeoapi server to be available."""
    for _ in range(45):
        try:
            r = requests.get(f"{BASE_URL}/", timeout=3)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    pytest.fail("pygeoapi server not available at localhost:5000")


class TestCollectionDiscovery:
    def test_landing_page(self):
        r = requests.get(f"{BASE_URL}/?f=json", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "links" in data

    def test_collections_list_contains_stations(self):
        r = requests.get(f"{BASE_URL}/collections?f=json", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        collection_ids = [c["id"] for c in data["collections"]]
        assert "stations" in collection_ids, (
            f"'stations' collection not found. Available: {collection_ids}"
        )

    def test_collection_metadata(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations?f=json", timeout=TIMEOUT
        )
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "stations"
        assert "extent" in data


class TestFeatureQuery:
    def test_items_returns_feature_collection(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json", timeout=TIMEOUT
        )
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 0

    def test_feature_structure(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=1",
            timeout=TIMEOUT,
        )
        data = r.json()
        feature = data["features"][0]
        assert feature["type"] == "Feature"
        assert "id" in feature
        assert "geometry" in feature
        assert feature["geometry"]["type"] == "Point"
        coords = feature["geometry"]["coordinates"]
        assert len(coords) >= 2
        assert "properties" in feature
        props = feature["properties"]
        assert "station_name" in props
        assert "station_type" in props

    def test_pagination_limit(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=5",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert len(data["features"]) == 5

    def test_pagination_offset(self):
        r1 = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=5&offset=0",
            timeout=TIMEOUT,
        )
        r2 = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=5&offset=5",
            timeout=TIMEOUT,
        )
        data1 = r1.json()
        data2 = r2.json()
        ids1 = {f["id"] for f in data1["features"]}
        ids2 = {f["id"] for f in data2["features"]}
        assert len(ids1) == 5
        assert len(ids2) == 5
        assert len(ids1 & ids2) == 0, "Offset pages should not overlap"

    def test_number_matched(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=5",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert "numberMatched" in data
        assert data["numberMatched"] == 25
        assert data["numberReturned"] == 5

    def test_resulttype_hits(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&resulttype=hits",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert "numberMatched" in data
        assert data["numberMatched"] == 25
        assert len(data["features"]) == 0


class TestBboxFilter:
    def test_bbox_north_america(self):
        """bbox covering contiguous North America should return 5 stations."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&bbox=-130,20,-60,50&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 5, (
            f"Expected 5 North American stations, got {len(features)}"
        )
        for f in features:
            lon, lat = f["geometry"]["coordinates"][:2]
            assert -130 <= lon <= -60, f"Longitude {lon} outside bbox"
            assert 20 <= lat <= 50, f"Latitude {lat} outside bbox"

    def test_bbox_europe(self):
        """bbox covering Western/Central Europe should return 5 stations."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&bbox=-10,35,20,55&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 5, (
            f"Expected 5 European stations, got {len(features)}"
        )
        for f in features:
            lon, lat = f["geometry"]["coordinates"][:2]
            assert -10 <= lon <= 20
            assert 35 <= lat <= 55

    def test_bbox_empty_result(self):
        """bbox over empty ocean should return 0 features."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&bbox=-30,-30,-20,-20&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert len(data["features"]) == 0

    def test_number_matched_with_bbox(self):
        """numberMatched must reflect the filtered count, not total."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&bbox=-130,20,-60,50&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert data["numberMatched"] == 5, (
            f"numberMatched should be 5 with bbox filter, got {data['numberMatched']}"
        )


class TestPropertyFilter:
    def test_filter_by_station_type_wind(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&station_type=wind&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 7, (
            f"Expected 7 wind stations, got {len(features)}"
        )
        for f in features:
            assert f["properties"]["station_type"] == "wind"

    def test_filter_by_status_inactive(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&status=inactive&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 4, (
            f"Expected 4 inactive stations, got {len(features)}"
        )
        for f in features:
            assert f["properties"]["status"] == "inactive"

    def test_number_matched_with_property_filter(self):
        """numberMatched must reflect the filtered count."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&station_type=wind&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert data["numberMatched"] == 7, (
            f"numberMatched should be 7 for wind filter, got {data['numberMatched']}"
        )


class TestSingleItem:
    def test_get_item_by_id(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items/1?f=json", timeout=TIMEOUT
        )
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "Feature"
        assert str(data["id"]) == "1"
        assert data["properties"]["station_name"] == "NOAA-SFO-01"
        coords = data["geometry"]["coordinates"]
        assert abs(coords[0] - (-122.4194)) < 0.01
        assert abs(coords[1] - 37.7749) < 0.01

    def test_get_nonexistent_item(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations/items/9999?f=json",
            timeout=TIMEOUT,
        )
        assert r.status_code in [400, 404, 500]


class TestDatetimeFilter:
    def test_datetime_range_jan_feb(self):
        """Stations with observation_time in Jan-Feb 2024."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json"
            f"&datetime=2024-01-01T00:00:00Z/2024-02-28T23:59:59Z&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 10, (
            f"Expected 10 stations in Jan-Feb, got {len(features)}"
        )
        for f in features:
            obs = f["properties"]["observation_time"]
            assert obs >= "2024-01-01" and obs < "2024-03-01"

    def test_datetime_open_start(self):
        """Open-start range: all observations up to end of February."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json"
            f"&datetime=../2024-02-28T23:59:59Z&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 10
        for f in features:
            obs = f["properties"]["observation_time"]
            assert obs <= "2024-03-01"

    def test_datetime_open_end(self):
        """Open-end range: all observations from May onward."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json"
            f"&datetime=2024-05-01T00:00:00Z/..&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        features = data["features"]
        assert len(features) == 5, (
            f"Expected 5 stations from May onward, got {len(features)}"
        )

    def test_number_matched_with_datetime(self):
        """numberMatched must reflect the datetime-filtered count."""
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json"
            f"&datetime=2024-01-01T00:00:00Z/2024-02-28T23:59:59Z&limit=50",
            timeout=TIMEOUT,
        )
        data = r.json()
        assert data["numberMatched"] == 10, (
            f"numberMatched should be 10 with datetime filter, got {data['numberMatched']}"
        )


class TestCRSSupport:
    def test_collection_advertises_crs(self):
        r = requests.get(
            f"{BASE_URL}/collections/stations?f=json", timeout=TIMEOUT
        )
        data = r.json()
        assert "crs" in data, "Collection must advertise supported CRS list"
        crs_list = data["crs"]
        has_3857 = any("3857" in c for c in crs_list)
        assert has_3857, f"EPSG:3857 not in CRS list: {crs_list}"

    def test_crs_request_accepted(self):
        """Requesting items with crs=EPSG:3857 should return 200."""
        crs_uri = "http://www.opengis.net/def/crs/EPSG/0/3857"
        r = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json&limit=1&crs={crs_uri}",
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["features"]) > 0


class TestTransactions:
    def test_create_update_delete_lifecycle(self):
        """Full CRUD lifecycle: create a feature, update it, delete it."""
        new_feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [10.0, 50.0]},
            "properties": {
                "station_name": "TEST-CRUD-01",
                "station_type": "temperature",
                "elevation_m": 100.0,
                "observation_time": "2024-06-20T12:00:00Z",
                "latest_value": 20.5,
                "status": "active",
            },
        }

        # CREATE
        r_create = requests.post(
            f"{BASE_URL}/collections/stations/items",
            json=new_feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=TIMEOUT,
        )
        assert r_create.status_code in [200, 201, 204], (
            f"Create failed: {r_create.status_code} {r_create.text[:200]}"
        )

        # Find the created item by its unique name
        r_find = requests.get(
            f"{BASE_URL}/collections/stations/items?f=json"
            f"&station_name=TEST-CRUD-01&limit=50",
            timeout=TIMEOUT,
        )
        find_data = r_find.json()
        assert len(find_data["features"]) >= 1, "Created feature not found"
        created_id = find_data["features"][0]["id"]

        # UPDATE
        update_feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [11.0, 51.0]},
            "properties": {
                "station_name": "TEST-UPDATED-01",
                "station_type": "temperature",
                "elevation_m": 200.0,
                "observation_time": "2024-06-20T12:00:00Z",
                "latest_value": 25.0,
                "status": "active",
            },
        }
        r_update = requests.put(
            f"{BASE_URL}/collections/stations/items/{created_id}",
            json=update_feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=TIMEOUT,
        )
        assert r_update.status_code in [200, 204], (
            f"Update failed: {r_update.status_code} {r_update.text[:200]}"
        )

        # Verify update
        r_verify = requests.get(
            f"{BASE_URL}/collections/stations/items/{created_id}?f=json",
            timeout=TIMEOUT,
        )
        assert r_verify.status_code == 200
        updated_data = r_verify.json()
        assert updated_data["properties"]["station_name"] == "TEST-UPDATED-01"
        assert updated_data["properties"]["elevation_m"] == 200.0

        # DELETE
        r_delete = requests.delete(
            f"{BASE_URL}/collections/stations/items/{created_id}",
            timeout=TIMEOUT,
        )
        assert r_delete.status_code in [200, 204], (
            f"Delete failed: {r_delete.status_code} {r_delete.text[:200]}"
        )

        # Verify deletion
        r_gone = requests.get(
            f"{BASE_URL}/collections/stations/items/{created_id}?f=json",
            timeout=TIMEOUT,
        )
        assert r_gone.status_code in [400, 404, 500]
