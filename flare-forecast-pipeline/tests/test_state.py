
"""
Tests for solar flare catalog spatial analysis pipeline.
Verifies coordinate correction, Carrington conversion, and derived outputs.
"""

import json
import os

import numpy as np
import pandas as pd
import pytest
from astropy.time import Time


# =========================================================
# Helpers
# =========================================================

def compute_cr_l0(jd):
    """Reference Carrington rotation number and L0 from Julian Date."""
    cr = (jd - 2398167.4) / 27.2753 + 1.0
    l0 = 360.0 * (np.ceil(cr) - cr)
    return cr, l0


def parse_location_ref(loc_str):
    """Parse SSW location string to (lat, lon) — independent reference."""
    s = str(loc_str).strip()
    if len(s) < 6:
        return None, None
    ns = s[0]
    lat_deg = int(s[1:3])
    ew = s[3]
    lon_deg = int(s[4:6])
    lat = lat_deg if ns == 'N' else -lat_deg
    lon = lon_deg if ew == 'W' else -lon_deg
    return lat, lon


# =========================================================
# Fixtures
# =========================================================

@pytest.fixture(scope="module")
def audit():
    with open('/app/output/coordinate_audit.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def catalog():
    df = pd.read_csv('/app/output/corrected_catalog.csv')
    df['event_starttime'] = pd.to_datetime(df['event_starttime'])
    # Ensure has_coords is boolean (CSV may read as string)
    if df['has_coords'].dtype == object:
        df['has_coords'] = df['has_coords'].str.strip().str.lower() == 'true'
    return df


@pytest.fixture(scope="module")
def rotation_profile():
    return pd.read_csv('/app/output/rotation_profile.csv')


@pytest.fixture(scope="module")
def geoeffective():
    return pd.read_csv('/app/output/geoeffective_events.csv')


@pytest.fixture(scope="module")
def ar_summary():
    return pd.read_csv('/app/output/ar_summary.csv')


@pytest.fixture(scope="module")
def raw_catalog():
    df = pd.read_csv('/app/data/flare_catalog.csv')
    df['event_starttime'] = pd.to_datetime(df['event_starttime'])
    return df


# =========================================================
# 1. File existence
# =========================================================

class TestOutputExists:
    def test_audit(self):
        assert os.path.isfile('/app/output/coordinate_audit.json')

    def test_catalog(self):
        assert os.path.isfile('/app/output/corrected_catalog.csv')

    def test_rotation(self):
        assert os.path.isfile('/app/output/rotation_profile.csv')

    def test_geoeffective(self):
        assert os.path.isfile('/app/output/geoeffective_events.csv')

    def test_ar_summary(self):
        assert os.path.isfile('/app/output/ar_summary.csv')


# =========================================================
# 2. Coordinate audit
# =========================================================

class TestAudit:
    def test_total_events(self, audit, raw_catalog):
        assert audit['total_events'] == len(raw_catalog)

    def test_has_quality_issues(self, audit):
        """The agent should discover coordinate data quality issues."""
        assert len(audit['data_quality_issues']) > 0, \
            "No data quality issues reported, but the catalog has a lat/lon column swap"

    def test_events_no_coords_reasonable(self, audit):
        assert audit['events_no_coords'] >= 0
        assert audit['events_no_coords'] < audit['total_events']

    def test_events_with_coords_majority(self, audit):
        assert audit['events_with_any_coords'] > audit['total_events'] * 0.5


# =========================================================
# 3. Corrected catalog structure
# =========================================================

class TestCatalogStructure:
    def test_columns(self, catalog):
        required = {'event_starttime', 'fl_goescls', 'ar_noaanum',
                     'hgs_lat', 'hgs_lon', 'hgc_lat', 'hgc_lon',
                     'carrington_rotation', 'coord_source', 'has_coords'}
        assert required.issubset(set(catalog.columns)), \
            f"Missing columns: {required - set(catalog.columns)}"

    def test_row_count(self, catalog, raw_catalog):
        assert len(catalog) == len(raw_catalog), \
            f"Catalog has {len(catalog)} rows, expected {len(raw_catalog)}"

    def test_hgs_lat_range(self, catalog):
        valid = catalog[catalog['has_coords'] == True]
        assert valid['hgs_lat'].between(-90, 90).all(), \
            "hgs_lat values outside [-90, 90]"

    def test_hgs_lon_range(self, catalog):
        valid = catalog[catalog['has_coords'] == True]
        assert valid['hgs_lon'].between(-180, 180).all(), \
            "hgs_lon values outside [-180, 180]"

    def test_hgc_lon_range(self, catalog):
        valid = catalog[catalog['has_coords'] == True]
        hgc = valid['hgc_lon'].dropna()
        assert (hgc >= 0).all() and (hgc < 360).all(), \
            "hgc_lon values outside [0, 360)"

    def test_hgc_lat_range(self, catalog):
        valid = catalog[catalog['has_coords'] == True]
        hgc = valid['hgc_lat'].dropna()
        assert hgc.between(-90, 90).all(), \
            "hgc_lat values outside [-90, 90]"

    def test_has_coords_consistency(self, catalog):
        """has_coords should be True iff hgs_lat and hgs_lon are non-null."""
        has = catalog['has_coords'] == True
        has_data = catalog['hgs_lat'].notna() & catalog['hgs_lon'].notna()
        assert (has == has_data).all()


# =========================================================
# 4. Coordinate swap correction verified via spot-checks
# =========================================================

class TestCoordinateCorrectness:
    """Verify the coordinate swap was detected and corrected by checking
    corrected coordinates against known location_ssw strings."""

    SPOT_CHECKS = [
        # (event_starttime, location_ssw, expected_hgs_lat, expected_hgs_lon)
        ("2010-05-01 01:34:00", "N24E77", 24.0, -77.0),
        ("2010-05-04 16:15:00", "N41W23", 41.0, 23.0),
        ("2010-05-02 15:09:00", "S17E88", -17.0, -88.0),
        ("2010-05-03 12:52:00", "N16W47", 16.0, 47.0),
        ("2010-05-05 17:13:00", "N42W36", 42.0, 36.0),
    ]

    @pytest.mark.parametrize("ts,loc,exp_lat,exp_lon", SPOT_CHECKS)
    def test_spot_check_hgs(self, catalog, ts, loc, exp_lat, exp_lon):
        row = catalog[catalog['event_starttime'] == pd.Timestamp(ts)]
        assert len(row) >= 1, f"Event {ts} not found"
        row = row.iloc[0]
        assert abs(row['hgs_lat'] - exp_lat) < 2.0, \
            f"At {ts} ({loc}): expected hgs_lat~{exp_lat}, got {row['hgs_lat']}"
        assert abs(row['hgs_lon'] - exp_lon) < 5.0, \
            f"At {ts} ({loc}): expected hgs_lon~{exp_lon}, got {row['hgs_lon']}"

    def test_swap_corrected_sign(self, catalog):
        """The event at 2010-05-01 01:34:00 has location N24E77.
        N24 means lat=+24 (positive). If the swap was NOT corrected,
        hgs_lat would be ~-73 (negative, from the raw lat_stony column)."""
        row = catalog[catalog['event_starttime'] == pd.Timestamp("2010-05-01 01:34:00")]
        assert len(row) >= 1
        row = row.iloc[0]
        assert row['hgs_lat'] > 0, \
            f"Expected positive hgs_lat (N24), got {row['hgs_lat']} — swap not corrected"

    def test_west_longitude_positive(self, catalog):
        """The event at 2010-05-03 12:52:00 has location N16W47.
        W47 means lon=+47 in west-positive convention."""
        row = catalog[catalog['event_starttime'] == pd.Timestamp("2010-05-03 12:52:00")]
        assert len(row) >= 1
        row = row.iloc[0]
        assert row['hgs_lon'] > 0, \
            f"Expected positive hgs_lon (W47), got {row['hgs_lon']}"


# =========================================================
# 5. Carrington conversion verification
# =========================================================

class TestCarringtonConversion:
    """Independently verify HGC longitude for spot-check events."""

    VERIFY_EVENTS = [
        # (event_starttime, correct_hgs_lat, correct_hgs_lon)
        ("2010-05-01 01:34:00", 24.0, -77.0),
        ("2010-05-04 16:15:00", 41.0, 23.0),
        ("2010-05-03 12:52:00", 16.0, 47.0),
    ]

    @pytest.mark.parametrize("ts_str,hgs_lat,hgs_lon", VERIFY_EVENTS)
    def test_hgc_conversion(self, catalog, ts_str, hgs_lat, hgs_lon):
        ts = pd.Timestamp(ts_str)
        row = catalog[catalog['event_starttime'] == ts]
        assert len(row) >= 1
        row = row.iloc[0]

        # Independent computation
        t = Time(ts_str)
        jd = t.jd
        _, l0 = compute_cr_l0(jd)
        expected_hgc_lon = (hgs_lon + l0) % 360.0

        assert abs(row['hgc_lon'] - expected_hgc_lon) < 3.0, \
            f"At {ts}: expected hgc_lon~{expected_hgc_lon:.1f}, got {row['hgc_lon']:.1f}"

    def test_hgc_lat_equals_hgs_lat(self, catalog):
        """Carrington latitude should match Stonyhurst latitude."""
        valid = catalog[catalog['has_coords'] == True]
        sample = valid.sample(min(500, len(valid)), random_state=42)
        diff = (sample['hgc_lat'] - sample['hgs_lat']).abs()
        assert diff.max() < 0.01, f"HGC lat != HGS lat, max diff={diff.max()}"

    def test_cr_range(self, catalog):
        """Carrington rotation numbers for 2010-2024 should be ~2095-2295."""
        valid = catalog[catalog['carrington_rotation'] > 0]
        assert valid['carrington_rotation'].min() >= 2090
        assert valid['carrington_rotation'].max() <= 2300

    def test_cr_monotonic(self, catalog):
        """CR numbers should generally increase with time."""
        valid = catalog[catalog['carrington_rotation'] > 0].sort_values('event_starttime')
        q1 = valid.iloc[:len(valid) // 4]['carrington_rotation'].median()
        q4 = valid.iloc[-len(valid) // 4:]['carrington_rotation'].median()
        assert q1 < q4, f"CR not monotonic: first-quarter median={q1}, last-quarter={q4}"


# =========================================================
# 6. Rotation profile
# =========================================================

class TestRotationProfile:
    def test_columns(self, rotation_profile):
        required = {'carrington_rotation', 'total_flares', 'a_class', 'b_class',
                     'c_class', 'm_class', 'x_class', 'total_goes_flux',
                     'peak_activity_longitude'}
        assert required.issubset(set(rotation_profile.columns)), \
            f"Missing: {required - set(rotation_profile.columns)}"

    def test_cr_range(self, rotation_profile):
        assert rotation_profile['carrington_rotation'].min() >= 2090
        assert rotation_profile['carrington_rotation'].max() <= 2300

    def test_total_flares_sum(self, rotation_profile, raw_catalog):
        """Total flares across all rotations should match catalog size."""
        total = rotation_profile['total_flares'].sum()
        assert total == len(raw_catalog), \
            f"Sum of total_flares={total}, expected {len(raw_catalog)}"

    def test_class_counts_consistency(self, rotation_profile):
        """Sum of class counts should equal total_flares per rotation."""
        for _, row in rotation_profile.iterrows():
            class_sum = row['a_class'] + row['b_class'] + row['c_class'] + \
                        row['m_class'] + row['x_class']
            assert class_sum == row['total_flares'], \
                f"CR {row['carrington_rotation']}: class sum {class_sum} != total {row['total_flares']}"

    def test_peak_longitude_range(self, rotation_profile):
        valid = rotation_profile.dropna(subset=['peak_activity_longitude'])
        if len(valid) > 0:
            assert (valid['peak_activity_longitude'] >= 0).all()
            assert (valid['peak_activity_longitude'] < 360).all()

    def test_flux_positive(self, rotation_profile):
        assert (rotation_profile['total_goes_flux'] >= 0).all()


# =========================================================
# 7. Geoeffective events
# =========================================================

class TestGeoeffective:
    def test_only_mx_class(self, geoeffective):
        classes = geoeffective['fl_goescls'].str[0].str.upper()
        assert classes.isin(['M', 'X']).all(), \
            f"Non-M/X classes found: {classes[~classes.isin(['M', 'X'])].unique()}"

    def test_score_range(self, geoeffective):
        assert (geoeffective['geo_score'] >= 0).all()
        assert (geoeffective['geo_score'] <= 1).all()

    def test_angular_distance_range(self, geoeffective):
        assert (geoeffective['angular_distance_deg'] >= 0).all()
        assert (geoeffective['angular_distance_deg'] <= 180).all()

    def test_score_distance_anticorrelation(self, geoeffective):
        """Higher angular distance should correlate with lower geo_score."""
        if len(geoeffective) > 10:
            corr = geoeffective['angular_distance_deg'].corr(geoeffective['geo_score'])
            assert corr < -0.5, f"Expected strong negative correlation, got {corr}"

    def test_disk_center_high_score(self, geoeffective):
        """Events near disk center should have high geo_score."""
        near_center = geoeffective[geoeffective['angular_distance_deg'] < 30]
        if len(near_center) > 0:
            assert near_center['geo_score'].min() > 0.5

    def test_independent_score_check(self, geoeffective):
        """Independently verify geo_score for a sample of events."""
        sample = geoeffective.head(min(20, len(geoeffective)))
        for _, row in sample.iterrows():
            lat_r = np.radians(row['hgs_lat'])
            lon_r = np.radians(row['hgs_lon'])
            cos_theta = np.cos(lat_r) * np.cos(lon_r)
            expected_dist = np.degrees(np.arccos(np.clip(cos_theta, -1, 1)))
            expected_score = max(0.0, cos_theta)
            assert abs(row['angular_distance_deg'] - expected_dist) < 1.0, \
                f"angular_distance mismatch: {row['angular_distance_deg']} vs {expected_dist}"
            assert abs(row['geo_score'] - expected_score) < 0.05, \
                f"geo_score mismatch: {row['geo_score']} vs {expected_score}"

    def test_has_coordinates(self, geoeffective):
        """All geoeffective events should have valid coordinates."""
        assert geoeffective['hgs_lat'].notna().all()
        assert geoeffective['hgs_lon'].notna().all()
        assert geoeffective['hgc_lon'].notna().all()


# =========================================================
# 8. AR summary
# =========================================================

class TestARSummary:
    def test_columns(self, ar_summary):
        required = {'ar_noaanum', 'total_flares', 'c_class', 'm_class', 'x_class',
                     'total_goes_flux', 'mean_hgc_lon', 'first_seen', 'last_seen'}
        assert required.issubset(set(ar_summary.columns)), \
            f"Missing: {required - set(ar_summary.columns)}"

    def test_noaa_numbers_valid(self, ar_summary):
        assert (ar_summary['ar_noaanum'] > 0).all()

    def test_flare_counts_positive(self, ar_summary):
        assert (ar_summary['total_flares'] > 0).all()

    def test_class_sum_leq_total(self, ar_summary):
        """C+M+X counts should not exceed total (A/B also counted)."""
        cmx = ar_summary['c_class'] + ar_summary['m_class'] + ar_summary['x_class']
        assert (cmx <= ar_summary['total_flares']).all()

    def test_mean_hgc_lon_range(self, ar_summary):
        valid = ar_summary.dropna(subset=['mean_hgc_lon'])
        if len(valid) > 0:
            assert (valid['mean_hgc_lon'] >= 0).all()
            assert (valid['mean_hgc_lon'] < 360).all()

    def test_dates_order(self, ar_summary):
        """first_seen should be <= last_seen."""
        for _, row in ar_summary.iterrows():
            assert pd.Timestamp(row['first_seen']) <= pd.Timestamp(row['last_seen'])

    def test_flux_positive(self, ar_summary):
        assert (ar_summary['total_goes_flux'] > 0).all()
