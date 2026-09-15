"""Tests for CMIP6 climate data pipeline.

Verifies Zarr store structure, ESM catalog format, and numerical analysis
results against independently computed expected values.
"""

import csv
import json
import os

import numpy as np
import pytest
import xarray as xr
import zarr

MODELS = ["MODEL-A", "MODEL-B", "MODEL-C"]
VARIABLES = ["tas", "hurs", "tos"]
RAW_DIR = "/data/raw_data"
ZARR_DIR = "/app/zarr_stores"


# ---------------------------------------------------------------------------
# Zarr store tests
# ---------------------------------------------------------------------------
class TestZarrStores:

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_store_exists(self, model, variable):
        path = os.path.join(ZARR_DIR, model, variable)
        assert os.path.isdir(path), f"Missing Zarr store: {path}"

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_dimensions(self, model, variable):
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, variable))
        assert variable in ds.data_vars
        arr = ds[variable]
        assert set(arr.dims) == {"time", "lat", "lon"}
        assert arr.sizes["time"] == 120
        assert arr.sizes["lat"] == 36
        assert arr.sizes["lon"] == 72

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_chunking(self, model, variable):
        z = zarr.open(os.path.join(ZARR_DIR, model, variable), mode="r")
        arr = z[variable]
        assert arr.chunks[0] == 12, f"Time chunk should be 12, got {arr.chunks[0]}"
        assert arr.chunks[1] == 36, f"Lat should be unchunked (36), got {arr.chunks[1]}"
        assert arr.chunks[2] == 72, f"Lon should be unchunked (72), got {arr.chunks[2]}"

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_compression(self, model, variable):
        z = zarr.open(os.path.join(ZARR_DIR, model, variable), mode="r")
        arr = z[variable]
        comp = arr.compressor
        assert comp is not None, "No compressor configured"
        assert comp.cname == "zstd", f"Expected zstd, got {comp.cname}"
        assert comp.clevel == 3, f"Expected clevel 3, got {comp.clevel}"

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_consolidated_metadata(self, model, variable):
        zpath = os.path.join(ZARR_DIR, model, variable, ".zmetadata")
        assert os.path.isfile(zpath), f"Missing consolidated metadata: {zpath}"

    @pytest.mark.parametrize("model", MODELS)
    @pytest.mark.parametrize("variable", VARIABLES)
    def test_cf_attributes(self, model, variable):
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, variable))
        attrs = ds[variable].attrs
        for key in ("units", "long_name", "standard_name"):
            assert key in attrs, f"Missing CF attribute '{key}' on {model}/{variable}"

    @pytest.mark.parametrize("model", MODELS)
    def test_units_normalized(self, model):
        # tas in Kelvin
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, "tas"))
        assert ds["tas"].attrs["units"] == "K"
        assert float(ds["tas"].mean()) > 200, "tas values too low for Kelvin"

        # hurs in percent
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, "hurs"))
        assert ds["hurs"].attrs["units"] == "%"
        assert float(ds["hurs"].mean()) > 1.0, "hurs values look fractional, not percent"

        # tos in Kelvin
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, "tos"))
        assert ds["tos"].attrs["units"] == "K"

    @pytest.mark.parametrize("model", MODELS)
    def test_time_coordinate(self, model):
        ds = xr.open_zarr(os.path.join(ZARR_DIR, model, "tas"))
        t0 = str(ds.time.values[0])
        assert t0.startswith("2000-01"), f"First timestep should be 2000-01, got {t0}"


# ---------------------------------------------------------------------------
# ESM catalog tests
# ---------------------------------------------------------------------------
class TestCatalog:

    def test_json_exists(self):
        assert os.path.isfile("/app/catalog.json")

    def test_csv_exists(self):
        assert os.path.isfile("/app/catalog.csv")

    def test_json_schema(self):
        with open("/app/catalog.json") as f:
            cat = json.load(f)

        assert cat.get("esmcat_version") == "0.1.0"
        for field in ("id", "description", "catalog_file", "attributes", "assets"):
            assert field in cat, f"Missing field '{field}' in catalog.json"

        attr_cols = {a["column_name"] for a in cat["attributes"]}
        for col in ("source_id", "experiment_id", "variable_id", "member_id"):
            assert col in attr_cols, f"Missing attribute column '{col}'"

        assert cat["assets"]["column_name"] == "zstore"
        assert cat["assets"]["format"] == "zarr"

    def test_csv_rows(self):
        with open("/app/catalog.csv") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 9, f"Expected 9 rows (3 models x 3 vars), got {len(rows)}"

        for row in rows:
            assert row["source_id"] in MODELS
            assert row["experiment_id"] == "historical"
            assert row["variable_id"] in VARIABLES
            assert row["member_id"] == "r1i1p1f1"
            assert os.path.isdir(row["zstore"]), f"Store path missing: {row['zstore']}"


# ---------------------------------------------------------------------------
# Numerical results tests
# ---------------------------------------------------------------------------
def _compute_wbt(T_celsius, RH_percent):
    """Stull (2011) wet-bulb temperature approximation."""
    T = T_celsius
    RH = RH_percent
    return (T * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
            + np.arctan(T + RH)
            - np.arctan(RH - 1.676331)
            + 0.00391838 * np.power(RH, 1.5) * np.arctan(0.023101 * RH)
            - 4.686035)


def _compute_expected():
    """Independently compute expected results from raw data."""
    wbt_means = {}
    oni_pos_list = []
    oni_neg_list = []
    enso_amp_list = []
    heat_stress_frac_list = []
    sst_trend_list = []

    for model in MODELS:
        mdir = os.path.join(RAW_DIR, model)
        with open(os.path.join(mdir, "metadata.json")) as f:
            meta = json.load(f)

        tas_raw = np.load(os.path.join(mdir, "tas.npy"))
        hurs_raw = np.load(os.path.join(mdir, "hurs.npy"))
        tos_raw = np.load(os.path.join(mdir, "tos.npy"))

        lats = np.array(meta["dimensions"]["lat"]["values"])
        lons = np.array(meta["dimensions"]["lon"]["values"])
        ntime = meta["dimensions"]["time"]["size"]
        nlat = len(lats)
        nlon = len(lons)

        # Normalise units
        if meta["variables"]["tas"]["units"] == "degC":
            tas_K = tas_raw + 273.15
        else:
            tas_K = tas_raw
        if meta["variables"]["hurs"]["units"] == "1":
            hurs_pct = hurs_raw * 100.0
        else:
            hurs_pct = hurs_raw

        # --- WBT ---
        T_C = tas_K - 273.15
        wbt = _compute_wbt(T_C, hurs_pct)
        cos_w = np.cos(np.deg2rad(lats))
        wbt_lon = np.nanmean(wbt, axis=2)          # (ntime, nlat)
        wbt_global = np.average(wbt_lon, weights=cos_w, axis=1)  # (ntime,)
        wbt_means[model] = float(np.mean(wbt_global))

        # --- Tropical heat stress ---
        tropical_mask = np.abs(lats) <= 23.5
        wbt_tropical = wbt[:, tropical_mask, :]
        n_total = wbt_tropical.size
        n_exceed = int(np.sum(wbt_tropical > 28.0))
        heat_stress_frac_list.append(float(n_exceed) / float(n_total))

        # --- ONI ---
        lat_sel = (lats >= -5) & (lats <= 5)
        lon_sel = (lons >= 190) & (lons <= 240)
        nino34 = tos_raw[:, lat_sel, :][:, :, lon_sel]
        nino_w = np.cos(np.deg2rad(lats[lat_sel]))

        nino_mean = np.zeros(ntime)
        for t in range(ntime):
            fld = nino34[t]
            w2d = np.broadcast_to(nino_w[:, None], fld.shape)
            nino_mean[t] = np.average(fld, weights=w2d)

        clim = np.array([np.mean(nino_mean[m::12]) for m in range(12)])
        anom = np.array([nino_mean[t] - clim[t % 12] for t in range(ntime)])
        rolling = np.convolve(anom, np.ones(3) / 3, mode="valid")

        oni_pos_list.append(int(np.sum(rolling > 0.5)))
        oni_neg_list.append(int(np.sum(rolling < -0.5)))
        enso_amp_list.append(float(np.std(rolling, ddof=0)))

        # --- SST global trend ---
        lat_weights_2d = np.broadcast_to(cos_w[:, None], (nlat, nlon))
        sst_ts = np.zeros(ntime)
        for t in range(ntime):
            field = tos_raw[t]
            valid = ~np.isnan(field)
            sst_ts[t] = np.average(field[valid], weights=lat_weights_2d[valid])

        t_months = np.arange(ntime, dtype=float)
        coeffs = np.polyfit(t_months, sst_ts, 1)
        slope_per_month = coeffs[0]
        trend_per_decade = slope_per_month * 120.0
        sst_trend_list.append(float(trend_per_decade))

    vals = list(wbt_means.values())
    return {
        "wbt_global_mean": round(float(np.mean(vals)), 4),
        "wbt_model_means": {k: round(v, 4) for k, v in wbt_means.items()},
        "oni_positive_months": round(float(np.mean(oni_pos_list)), 4),
        "oni_negative_months": round(float(np.mean(oni_neg_list)), 4),
        "ensemble_wbt_spread": round(float(np.std(vals, ddof=0)), 4),
        "enso_amplitude": round(float(np.mean(enso_amp_list)), 4),
        "tropical_heat_stress_fraction": round(float(np.mean(heat_stress_frac_list)), 4),
        "sst_global_trend": round(float(np.mean(sst_trend_list)), 4),
    }


class TestResults:

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/results.json") as f:
            self.results = json.load(f)
        self.expected = _compute_expected()

    def test_file_exists(self):
        assert os.path.isfile("/app/results.json")

    def test_required_keys(self):
        for key in ("wbt_global_mean", "wbt_model_means",
                     "oni_positive_months", "oni_negative_months",
                     "ensemble_wbt_spread", "enso_amplitude",
                     "tropical_heat_stress_fraction", "sst_global_trend"):
            assert key in self.results, f"Missing key: {key}"

    def test_wbt_global_mean(self):
        assert abs(self.results["wbt_global_mean"]
                   - self.expected["wbt_global_mean"]) < 0.01

    def test_wbt_model_means(self):
        for model in MODELS:
            assert model in self.results["wbt_model_means"], \
                f"Missing model key: {model}"
            actual = self.results["wbt_model_means"][model]
            expected = self.expected["wbt_model_means"][model]
            assert abs(actual - expected) < 0.01, \
                f"{model}: got {actual}, expected {expected}"

    def test_oni_positive_months(self):
        assert abs(self.results["oni_positive_months"]
                   - self.expected["oni_positive_months"]) < 2.0

    def test_oni_negative_months(self):
        assert abs(self.results["oni_negative_months"]
                   - self.expected["oni_negative_months"]) < 2.0

    def test_ensemble_wbt_spread(self):
        assert abs(self.results["ensemble_wbt_spread"]
                   - self.expected["ensemble_wbt_spread"]) < 0.01

    def test_enso_amplitude(self):
        assert abs(self.results["enso_amplitude"]
                   - self.expected["enso_amplitude"]) < 0.05

    def test_tropical_heat_stress_fraction(self):
        assert abs(self.results["tropical_heat_stress_fraction"]
                   - self.expected["tropical_heat_stress_fraction"]) < 0.02

    def test_sst_global_trend(self):
        assert abs(self.results["sst_global_trend"]
                   - self.expected["sst_global_trend"]) < 0.02
