
import math
import os

import netCDF4
import numpy as np
import pytest
from xml.etree import ElementTree as ET

NC_FILE = "/app/output/profiles.nc"
XML_FILE = "/app/output/erddap_config.xml"

EXPECTED_STATIONS = {
    "CCS_M1": {"lat": 36.748, "lon": -122.022},
    "CCS_M2": {"lat": 36.697, "lon": -122.378},
    "CCS_CC": {"lat": 33.550, "lon": -118.400},
}

EXPECTED_PROFILES = {
    "CCS_M1_001": {"station": "CCS_M1", "n_obs": 6},
    "CCS_M1_002": {"station": "CCS_M1", "n_obs": 7},
    "CCS_M1_003": {"station": "CCS_M1", "n_obs": 6},
    "CCS_M2_001": {"station": "CCS_M2", "n_obs": 5},
    "CCS_M2_002": {"station": "CCS_M2", "n_obs": 6},
    "CCS_M2_003": {"station": "CCS_M2", "n_obs": 7},
    "CCS_CC_001": {"station": "CCS_CC", "n_obs": 6},
    "CCS_CC_002": {"station": "CCS_CC", "n_obs": 5},
    "CCS_CC_003": {"station": "CCS_CC", "n_obs": 6},
}


def depth_from_pressure(p, lat):
    """UNESCO 1983 (Fofonoff & Millard) pressure to depth."""
    x = math.sin(math.radians(lat))
    x = x * x
    gr = 9.780318 * (1.0 + (5.2788e-3 + 2.36e-5 * x) * x) + 1.092e-6 * p
    depth = (
        ((-1.82e-15 * p + 2.279e-10) * p - 2.2512e-5) * p + 9.72659
    ) * p
    return depth / gr


def is_missing(val):
    """Check if a netCDF value represents missing data."""
    if isinstance(val, np.ma.core.MaskedConstant):
        return True
    if hasattr(val, "mask"):
        if np.ndim(val.mask) == 0:
            return bool(val.mask)
        return bool(np.any(val.mask))
    try:
        return bool(np.isnan(float(val)))
    except (TypeError, ValueError):
        return False


def find_var_by_cf_role(ds, role):
    """Find a variable with the given cf_role attribute."""
    for vname in ds.variables:
        var = ds.variables[vname]
        if hasattr(var, "cf_role") and var.cf_role == role:
            return vname
    return None


def get_string_values(ds, var_name):
    """Read string values from a variable (handles VL strings and S1 char arrays)."""
    var = ds.variables[var_name]
    raw = var[:]
    if var.dtype == "S1":
        names = netCDF4.chartostring(raw)
        return [s.strip("\x00").strip() for s in names]
    return [str(s).strip() for s in raw]


def get_station_names(ds):
    ts_var = find_var_by_cf_role(ds, "timeseries_id")
    if ts_var is None:
        pytest.fail("No variable with cf_role='timeseries_id' found")
    return get_string_values(ds, ts_var)


def get_profile_ids(ds):
    pf_var = find_var_by_cf_role(ds, "profile_id")
    if pf_var is None:
        pytest.fail("No variable with cf_role='profile_id' found")
    return get_string_values(ds, pf_var)


def find_instance_dim_var(ds, dim_name):
    """Find the variable with instance_dimension=dim_name."""
    for vname in ds.variables:
        var = ds.variables[vname]
        if hasattr(var, "instance_dimension") and var.instance_dimension == dim_name:
            return vname
    return None


def find_sample_dim_var(ds, dim_name):
    """Find the variable with sample_dimension=dim_name."""
    for vname in ds.variables:
        var = ds.variables[vname]
        if hasattr(var, "sample_dimension") and var.sample_dimension == dim_name:
            return vname
    return None


def get_obs_range_for_profile(ds, profile_idx):
    """Get (start, end) observation indices for a profile using row_size."""
    rs_var = find_sample_dim_var(ds, "obs")
    if rs_var is None:
        pytest.fail("No variable with sample_dimension='obs' found")
    row_sizes = ds.variables[rs_var][:]
    start = int(np.sum(row_sizes[:profile_idx]))
    end = start + int(row_sizes[profile_idx])
    return start, end


def get_profile_idx_by_id(ds, target_id):
    """Find the index of a profile by its profile_id."""
    pids = get_profile_ids(ds)
    for i, pid in enumerate(pids):
        if pid == target_id:
            return i
    pytest.fail(f"Profile '{target_id}' not found in {pids}")


# ════════════════════════════════════════════════════════════════
# File Existence
# ════════════════════════════════════════════════════════════════


class TestFileExistence:
    def test_netcdf_file_exists(self):
        assert os.path.exists(NC_FILE), f"{NC_FILE} not found"

    def test_xml_file_exists(self):
        assert os.path.exists(XML_FILE), f"{XML_FILE} not found"


# ════════════════════════════════════════════════════════════════
# NetCDF Structure (timeSeriesProfile DSG)
# ════════════════════════════════════════════════════════════════


class TestNetCDFStructure:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_netcdf4_format(self, ds):
        assert ds.data_model in ("NETCDF4", "NETCDF4_CLASSIC")

    def test_station_dimension(self, ds):
        assert "station" in ds.dimensions
        assert len(ds.dimensions["station"]) == 3

    def test_profile_dimension(self, ds):
        assert "profile" in ds.dimensions
        assert len(ds.dimensions["profile"]) == 9

    def test_obs_dimension(self, ds):
        assert "obs" in ds.dimensions
        assert len(ds.dimensions["obs"]) == 54

    def test_station_index_with_instance_dim(self, ds):
        si_var = find_instance_dim_var(ds, "station")
        assert si_var is not None, "No variable with instance_dimension='station'"
        assert "profile" in ds.variables[si_var].dimensions

    def test_row_size_with_sample_dim(self, ds):
        rs_var = find_sample_dim_var(ds, "obs")
        assert rs_var is not None, "No variable with sample_dimension='obs'"
        assert "profile" in ds.variables[rs_var].dimensions

    def test_row_size_values(self, ds):
        """Each profile must have the correct number of observations."""
        rs_var = find_sample_dim_var(ds, "obs")
        row_sizes = ds.variables[rs_var][:]
        profile_ids = get_profile_ids(ds)
        for i, pid in enumerate(profile_ids):
            expected_n = EXPECTED_PROFILES[pid]["n_obs"]
            actual_n = int(row_sizes[i])
            assert actual_n == expected_n, (
                f"Profile {pid}: expected {expected_n} obs, got {actual_n}"
            )


# ════════════════════════════════════════════════════════════════
# CF Global Attributes
# ════════════════════════════════════════════════════════════════


class TestCFGlobalAttributes:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_conventions(self, ds):
        assert "Conventions" in ds.ncattrs()
        assert "CF-1.8" in ds.Conventions

    def test_feature_type(self, ds):
        assert "featureType" in ds.ncattrs()
        assert ds.featureType.lower() == "timeseriesprofile"


# ════════════════════════════════════════════════════════════════
# Station Variables
# ════════════════════════════════════════════════════════════════


class TestStationVariables:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_timeseries_id_cf_role(self, ds):
        ts_var = find_var_by_cf_role(ds, "timeseries_id")
        assert ts_var is not None

    def test_station_id_on_station_dim(self, ds):
        ts_var = find_var_by_cf_role(ds, "timeseries_id")
        assert "station" in ds.variables[ts_var].dimensions

    def test_all_station_names(self, ds):
        names = set(get_station_names(ds))
        assert names == set(EXPECTED_STATIONS.keys())

    def test_coordinate_values(self, ds):
        names = get_station_names(ds)
        lat = ds.variables["latitude"][:]
        lon = ds.variables["longitude"][:]
        for i, name in enumerate(names):
            exp = EXPECTED_STATIONS[name]
            assert abs(float(lat[i]) - exp["lat"]) < 0.001, f"{name} lat"
            assert abs(float(lon[i]) - exp["lon"]) < 0.001, f"{name} lon"

    def test_latitude_metadata(self, ds):
        lat = ds.variables["latitude"]
        assert lat.units == "degrees_north"
        assert lat.standard_name == "latitude"

    def test_longitude_metadata(self, ds):
        lon = ds.variables["longitude"]
        assert lon.units == "degrees_east"
        assert lon.standard_name == "longitude"


# ════════════════════════════════════════════════════════════════
# Profile Variables
# ════════════════════════════════════════════════════════════════


class TestProfileVariables:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_profile_id_cf_role(self, ds):
        pf_var = find_var_by_cf_role(ds, "profile_id")
        assert pf_var is not None

    def test_time_on_profile_dim(self, ds):
        assert "time" in ds.variables
        assert "profile" in ds.variables["time"].dimensions

    def test_time_numeric_with_epoch(self, ds):
        t = ds.variables["time"]
        assert t.dtype.kind in ("f", "i"), "Time must be numeric"
        assert hasattr(t, "units") and "since" in t.units and "1970" in t.units
        assert hasattr(t, "calendar")

    def test_station_index_maps_correctly(self, ds):
        """stationIndex must correctly link each profile to its station."""
        si_var = find_instance_dim_var(ds, "station")
        si_vals = ds.variables[si_var][:]
        station_names = get_station_names(ds)
        profile_ids = get_profile_ids(ds)
        for pi, pid in enumerate(profile_ids):
            expected_station = EXPECTED_PROFILES[pid]["station"]
            actual_station = station_names[int(si_vals[pi])]
            assert actual_station == expected_station, (
                f"Profile {pid}: expected station {expected_station}, "
                f"got {actual_station}"
            )

    def test_station_has_correct_profile_count(self, ds):
        si_var = find_instance_dim_var(ds, "station")
        si_vals = ds.variables[si_var][:]
        station_names = get_station_names(ds)
        for i, sname in enumerate(station_names):
            expected = sum(
                1 for info in EXPECTED_PROFILES.values()
                if info["station"] == sname
            )
            actual = int(np.sum(si_vals == i))
            assert actual == expected, (
                f"Station {sname}: expected {expected} profiles, got {actual}"
            )


# ════════════════════════════════════════════════════════════════
# Depth Computation (UNESCO 1983)
# ════════════════════════════════════════════════════════════════


class TestDepthComputation:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_depth_variable_exists(self, ds):
        assert "depth" in ds.variables
        assert "obs" in ds.variables["depth"].dimensions

    def test_depth_standard_name(self, ds):
        d = ds.variables["depth"]
        assert d.standard_name == "depth"
        assert d.units == "m"

    def test_depth_positive_down_axis_z(self, ds):
        d = ds.variables["depth"]
        assert hasattr(d, "positive") and d.positive == "down"
        assert hasattr(d, "axis") and d.axis == "Z"

    def test_depth_values_profile1_vs_unesco(self, ds):
        """Verify depth computed from pressure using UNESCO formula for CCS_M1_001."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_001")
        start, end = get_obs_range_for_profile(ds, pi)
        depths = ds.variables["depth"][start:end]
        pressures = ds.variables["pressure"][start:end]
        lat = EXPECTED_STATIONS["CCS_M1"]["lat"]

        for i in range(end - start):
            p = float(pressures[i])
            expected_depth = depth_from_pressure(p, lat)
            actual_depth = float(depths[i])
            assert abs(actual_depth - expected_depth) < 0.1, (
                f"Depth at p={p} dbar: expected {expected_depth:.2f}, "
                f"got {actual_depth:.2f}"
            )

    def test_depth_values_profile7_different_lat(self, ds):
        """Verify depth for CCS_CC_001 at a different latitude."""
        pi = get_profile_idx_by_id(ds, "CCS_CC_001")
        start, end = get_obs_range_for_profile(ds, pi)
        depths = ds.variables["depth"][start:end]
        pressures = ds.variables["pressure"][start:end]
        lat = EXPECTED_STATIONS["CCS_CC"]["lat"]

        for i in range(end - start):
            p = float(pressures[i])
            expected_depth = depth_from_pressure(p, lat)
            actual_depth = float(depths[i])
            assert abs(actual_depth - expected_depth) < 0.1, (
                f"Depth at p={p} dbar (lat={lat}): expected "
                f"{expected_depth:.2f}, got {actual_depth:.2f}"
            )


# ════════════════════════════════════════════════════════════════
# Temperature Data Fidelity
# ════════════════════════════════════════════════════════════════


class TestTemperatureData:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_temperature_values_profile1(self, ds):
        """Verify temperature values for CCS_M1_001."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_001")
        start, end = get_obs_range_for_profile(ds, pi)
        temp = ds.variables["temperature"][start:end]
        expected = [14.2, 13.8, 12.5, 10.1, 7.3, 4.8]
        for i, exp in enumerate(expected):
            assert not is_missing(temp[i]), f"Index {i}: unexpected missing"
            assert abs(float(temp[i]) - exp) < 0.05, (
                f"Index {i}: {temp[i]} != {exp}"
            )

    def test_temperature_missing_profile2(self, ds):
        """Verify NaN handling for CCS_M1_002 (index 2 missing)."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_002")
        start, end = get_obs_range_for_profile(ds, pi)
        temp = ds.variables["temperature"][start:end]
        assert is_missing(temp[2]), "Index 2 should be missing"
        assert not is_missing(temp[0]), "Index 0 should not be missing"
        assert abs(float(temp[0]) - 14.5) < 0.05

    def test_salinity_metadata(self, ds):
        sal = ds.variables["salinity"]
        assert sal.standard_name == "sea_water_practical_salinity"
        assert hasattr(sal, "coordinates")


# ════════════════════════════════════════════════════════════════
# QARTOD QC Variables
# ════════════════════════════════════════════════════════════════


class TestQCVariables:
    @pytest.fixture(scope="class")
    def ds(self):
        d = netCDF4.Dataset(NC_FILE, "r")
        yield d
        d.close()

    def test_ancillary_variables_on_temperature(self, ds):
        temp = ds.variables["temperature"]
        assert hasattr(temp, "ancillary_variables"), (
            "temperature missing ancillary_variables"
        )
        av = temp.ancillary_variables
        assert "temperature_gross_range_qc" in av
        assert "temperature_spike_qc" in av

    def test_gross_range_qc_flag_attrs(self, ds):
        qc = ds.variables["temperature_gross_range_qc"]
        assert hasattr(qc, "flag_values"), "Missing flag_values"
        assert hasattr(qc, "flag_meanings"), "Missing flag_meanings"
        fv = list(qc.flag_values)
        assert 1 in fv and 4 in fv

    def test_spike_qc_flag_attrs(self, ds):
        qc = ds.variables["temperature_spike_qc"]
        assert hasattr(qc, "flag_values"), "Missing flag_values"
        assert hasattr(qc, "flag_meanings"), "Missing flag_meanings"
        fv = list(qc.flag_values)
        assert 1 in fv and 2 in fv and 4 in fv

    def test_gross_range_qc_profile3_within_range(self, ds):
        """CCS_M1_003 has a spike (20.5 C) but within gross range -> all flags=1."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_003")
        start, end = get_obs_range_for_profile(ds, pi)
        qc = ds.variables["temperature_gross_range_qc"][start:end]
        expected = [1, 1, 1, 1, 1, 1]
        for i, exp in enumerate(expected):
            assert int(qc[i]) == exp, (
                f"Gross range QC at {i}: expected {exp}, got {int(qc[i])}"
            )

    def test_spike_qc_profile3_detects_spike(self, ds):
        """CCS_M1_003: spike at index 2 (T=20.5), adjacent affected."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_003")
        start, end = get_obs_range_for_profile(ds, pi)
        qc = ds.variables["temperature_spike_qc"][start:end]
        # Index 0: endpoint=2, Index 1: 3.75>2=suspect(3),
        # Index 2: 8.6>6=fail(4), Index 3: 3.5>2=suspect(3),
        # Index 4: 0.35=pass(1), Index 5: endpoint=2
        expected = [2, 3, 4, 3, 1, 2]
        for i, exp in enumerate(expected):
            assert int(qc[i]) == exp, (
                f"Spike QC at {i}: expected {exp}, got {int(qc[i])}"
            )

    def test_spike_qc_profile9_detects_spike(self, ds):
        """CCS_CC_003: spike at index 4 (T=18.5), adjacent affected."""
        pi = get_profile_idx_by_id(ds, "CCS_CC_003")
        start, end = get_obs_range_for_profile(ds, pi)
        qc = ds.variables["temperature_spike_qc"][start:end]
        # Index 0: endpoint=2, Index 1: 0.4=pass(1), Index 2: 0.65=pass(1),
        # Index 3: 5.05>2=suspect(3), Index 4: 10.4>6=fail(4),
        # Index 5: endpoint=2
        expected = [2, 1, 1, 3, 4, 2]
        for i, exp in enumerate(expected):
            assert int(qc[i]) == exp, (
                f"Spike QC at {i}: expected {exp}, got {int(qc[i])}"
            )

    def test_spike_qc_missing_profile2(self, ds):
        """CCS_M1_002: missing at index 2, adjacent get not_evaluated(2)."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_002")
        start, end = get_obs_range_for_profile(ds, pi)
        qc = ds.variables["temperature_spike_qc"][start:end]
        # Index 0: endpoint=2, Index 1: adj NaN=2, Index 2: NaN=9,
        # Index 3: adj NaN=2, Index 4: 0.35=pass(1), Index 5: 0.85=pass(1),
        # Index 6: endpoint=2
        expected = [2, 2, 9, 2, 1, 1, 2]
        for i, exp in enumerate(expected):
            assert int(qc[i]) == exp, (
                f"Spike QC at {i}: expected {exp}, got {int(qc[i])}"
            )

    def test_gross_range_qc_missing_profile2(self, ds):
        """CCS_M1_002: missing at index 2 -> gross range flag=9."""
        pi = get_profile_idx_by_id(ds, "CCS_M1_002")
        start, end = get_obs_range_for_profile(ds, pi)
        qc = ds.variables["temperature_gross_range_qc"][start:end]
        expected = [1, 1, 9, 1, 1, 1, 1]
        for i, exp in enumerate(expected):
            assert int(qc[i]) == exp, (
                f"Gross range QC at {i}: expected {exp}, got {int(qc[i])}"
            )


# ════════════════════════════════════════════════════════════════
# ERDDAP datasets.xml Configuration
# ════════════════════════════════════════════════════════════════


class TestERDDAPConfig:
    @pytest.fixture(scope="class")
    def tree(self):
        return ET.parse(XML_FILE)

    def test_root_is_dataset(self, tree):
        root = tree.getroot()
        assert root.tag == "dataset"

    def test_dataset_type(self, tree):
        root = tree.getroot()
        assert root.get("type") == "EDDTableFromNcCFFiles"

    def test_dataset_id(self, tree):
        root = tree.getroot()
        did = root.get("datasetID")
        assert did is not None and len(did) > 0

    def test_reload_minutes(self, tree):
        root = tree.getroot()
        elem = root.find(".//reloadEveryNMinutes")
        assert elem is not None, "Missing reloadEveryNMinutes"
        assert int(elem.text.strip()) > 0

    def test_cdm_data_type(self, tree):
        root = tree.getroot()
        att = root.find(".//att[@name='cdm_data_type']")
        assert att is not None, "Missing cdm_data_type attribute"
        assert att.text.strip() == "TimeSeriesProfile"

    def test_cdm_timeseries_variables(self, tree):
        root = tree.getroot()
        att = root.find(".//att[@name='cdm_timeseries_variables']")
        assert att is not None, "Missing cdm_timeseries_variables"
        text = att.text.strip()
        assert "latitude" in text
        assert "longitude" in text

    def test_cdm_profile_variables(self, tree):
        root = tree.getroot()
        att = root.find(".//att[@name='cdm_profile_variables']")
        assert att is not None, "Missing cdm_profile_variables"
        text = att.text.strip()
        assert "time" in text

    def test_feature_type_in_xml(self, tree):
        root = tree.getroot()
        att = root.find(".//att[@name='featureType']")
        assert att is not None, "Missing featureType attribute"
        assert att.text.strip().lower() == "timeseriesprofile"

    def test_data_variables_declared(self, tree):
        """Key variables must have dataVariable blocks."""
        root = tree.getroot()
        dvars = root.findall(".//dataVariable")
        source_names = []
        for dv in dvars:
            sn = dv.find("sourceName")
            if sn is not None:
                source_names.append(sn.text.strip())
        for required in [
            "time",
            "latitude",
            "longitude",
            "depth",
            "temperature",
            "salinity",
            "pressure",
        ]:
            assert required in source_names, (
                f"dataVariable '{required}' not declared"
            )
