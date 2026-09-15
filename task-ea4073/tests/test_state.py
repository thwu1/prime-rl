"""Verify CDO climate extremes pipeline outputs.

"""

import os
import subprocess
import numpy as np
import netCDF4 as nc

RESULTS = '/app/results'
DATA = '/app/data'


def cdo_run(cmd, check=True):
    """Run a CDO command silently with NetCDF classic output, return stdout."""
    r = subprocess.run(
        f"cdo -f nc -s {cmd}", shell=True, capture_output=True, text=True, timeout=120
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"CDO failed on '{cmd}': {r.stderr}")
    return r.stdout.strip()


def cdo_fldmean_val(fpath, ops=""):
    """Compute a single area-weighted field mean scalar via CDO output."""
    s = cdo_run(f"output -fldmean {ops} {fpath}")
    return float(s.strip().split()[-1])


def get_data_vars(ds):
    """Return variable names that are not coordinates or bounds."""
    skip = set(ds.dimensions.keys()) | {
        'time_bnds', 'lat_bnds', 'lon_bnds', 'bnds',
        'climatology_bounds', 'height', 'nv', 'nb2',
    }
    return [v for v in ds.variables if v not in skip]


# =====================================================================
#  1. Regridded output — structural and DNA checks
# =====================================================================
class TestRegrid:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/tasmax_regrid.nc'), \
            "tasmax_regrid.nc missing"

    def test_grid_size(self):
        ds = nc.Dataset(f'{RESULTS}/tasmax_regrid.nc', 'r')
        dvars = get_data_vars(ds)
        assert len(dvars) >= 1, "No data variables found"
        spatial = int(np.prod(ds.variables[dvars[0]].shape[1:]))
        ds.close()
        assert spatial == 648, f"Expected r36x18=648 grid points, got {spatial}"

    def test_timesteps(self):
        ds = nc.Dataset(f'{RESULTS}/tasmax_regrid.nc', 'r')
        assert ds.dimensions['time'].size == 3652, \
            f"Expected 3652 timesteps, got {ds.dimensions['time'].size}"
        ds.close()

    def test_value_range(self):
        ds = nc.Dataset(f'{RESULTS}/tasmax_regrid.nc', 'r')
        dvars = get_data_vars(ds)
        sample = ds.variables[dvars[0]][0, ...]
        ds.close()
        assert np.nanmin(sample) > 200, "Temperature below 200 K"
        assert np.nanmax(sample) < 340, "Temperature above 340 K"

    def test_dna_conservation_ts1(self):
        """Area-weighted field mean at timestep 1 must be preserved by
        conservative remapping (seed-42 specific value)."""
        raw = cdo_fldmean_val(f"{DATA}/tasmax_daily.nc", "-seltimestep,1")
        out = cdo_fldmean_val(f"{RESULTS}/tasmax_regrid.nc", "-seltimestep,1")
        assert abs(raw - out) < 0.05, \
            f"Conservation ts1: raw={raw:.4f}, regrid={out:.4f}"

    def test_dna_conservation_ts1826(self):
        """Area-weighted field mean at mid-period must be preserved."""
        raw = cdo_fldmean_val(f"{DATA}/tasmax_daily.nc", "-seltimestep,1826")
        out = cdo_fldmean_val(f"{RESULTS}/tasmax_regrid.nc", "-seltimestep,1826")
        assert abs(raw - out) < 0.05, \
            f"Conservation ts1826: raw={raw:.4f}, regrid={out:.4f}"

    def test_dna_conservation_ts3652(self):
        """Area-weighted field mean at final timestep must be preserved."""
        raw = cdo_fldmean_val(f"{DATA}/tasmax_daily.nc", "-seltimestep,3652")
        out = cdo_fldmean_val(f"{RESULTS}/tasmax_regrid.nc", "-seltimestep,3652")
        assert abs(raw - out) < 0.05, \
            f"Conservation ts3652: raw={raw:.4f}, regrid={out:.4f}"

    def test_dna_warming_trend_preserved(self):
        """The 0.3 K/yr warming trend must be preserved through remapping."""
        r1 = cdo_fldmean_val(f"{DATA}/tasmax_daily.nc", "-seltimestep,1")
        r2 = cdo_fldmean_val(f"{DATA}/tasmax_daily.nc", "-seltimestep,3652")
        o1 = cdo_fldmean_val(f"{RESULTS}/tasmax_regrid.nc", "-seltimestep,1")
        o2 = cdo_fldmean_val(f"{RESULTS}/tasmax_regrid.nc", "-seltimestep,3652")
        raw_trend = r2 - r1
        out_trend = o2 - o1
        assert abs(raw_trend - out_trend) < 0.1, \
            f"Trend mismatch: raw={raw_trend:.4f}, regrid={out_trend:.4f}"


# =====================================================================
#  2. 90th percentile — structural and DNA checks
# =====================================================================
class TestPctl90:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/pctl90.nc'), "pctl90.nc missing"

    def test_timesteps(self):
        ds = nc.Dataset(f'{RESULTS}/pctl90.nc', 'r')
        nt = ds.dimensions['time'].size
        ds.close()
        assert nt in (365, 366), f"Expected 365-366 day-of-year steps, got {nt}"

    def test_grid_matches_regrid(self):
        ds_p = nc.Dataset(f'{RESULTS}/pctl90.nc', 'r')
        ds_r = nc.Dataset(f'{RESULTS}/tasmax_regrid.nc', 'r')
        pv = get_data_vars(ds_p)
        rv = get_data_vars(ds_r)
        sp = int(np.prod(ds_p.variables[pv[0]].shape[1:]))
        sr = int(np.prod(ds_r.variables[rv[0]].shape[1:]))
        ds_p.close()
        ds_r.close()
        assert sp == sr, f"Grid mismatch: pctl={sp}, regrid={sr}"

    def test_dna_exceeds_raw_ref_mean(self):
        """90th percentile global mean must exceed the reference-period
        global mean from the raw data by 1-8 K (seed-42 specific)."""
        pctl_mean = cdo_fldmean_val(f"{RESULTS}/pctl90.nc", "-timmean")
        raw_ref = cdo_fldmean_val(
            f"{DATA}/tasmax_daily.nc", "-timmean -selyear,2001/2005"
        )
        excess = pctl_mean - raw_ref
        assert 1.0 < excess < 8.0, \
            f"Pctl90 excess: pctl={pctl_mean:.4f}, ref={raw_ref:.4f}, diff={excess:.4f}"

    def test_dna_value_range_tight(self):
        """Percentile values must be in physically meaningful range."""
        ds = nc.Dataset(f'{RESULTS}/pctl90.nc', 'r')
        dvars = get_data_vars(ds)
        data = ds.variables[dvars[0]][:]
        ds.close()
        assert np.nanmin(data) > 230, f"Pctl min {np.nanmin(data):.1f} too low"
        assert np.nanmax(data) < 330, f"Pctl max {np.nanmax(data):.1f} too high"


# =====================================================================
#  3. WSDI — structural and DNA checks
# =====================================================================
class TestWSDI:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/wsdi.nc'), "wsdi.nc missing"

    def test_timesteps(self):
        ds = nc.Dataset(f'{RESULTS}/wsdi.nc', 'r')
        nt = ds.dimensions['time'].size
        ds.close()
        assert nt == 5, f"Expected 5 yearly values (2006-2010), got {nt}"

    def test_nonnegative(self):
        ds = nc.Dataset(f'{RESULTS}/wsdi.nc', 'r')
        dvars = get_data_vars(ds)
        data = ds.variables[dvars[0]][:]
        ds.close()
        assert np.all(np.nan_to_num(data, nan=0) >= 0), \
            "WSDI must be non-negative"

    def test_grid_matches(self):
        ds_w = nc.Dataset(f'{RESULTS}/wsdi.nc', 'r')
        ds_r = nc.Dataset(f'{RESULTS}/tasmax_regrid.nc', 'r')
        wv = get_data_vars(ds_w)
        rv = get_data_vars(ds_r)
        sw = int(np.prod(ds_w.variables[wv[0]].shape[1:]))
        sr = int(np.prod(ds_r.variables[rv[0]].shape[1:]))
        ds_w.close()
        ds_r.close()
        assert sw == sr, f"WSDI grid ({sw}) != regrid grid ({sr})"

    def test_dna_positive_total(self):
        """Total WSDI across all grid points and years must be positive
        (warming trend in seed-42 data guarantees warm spells)."""
        ds = nc.Dataset(f'{RESULTS}/wsdi.nc', 'r')
        dvars = get_data_vars(ds)
        total = float(np.nansum(ds.variables[dvars[0]][:]))
        ds.close()
        assert total > 0, f"WSDI total = {total}, expected > 0"

    def test_dna_later_years_warmer(self):
        """WSDI spatial sum in 2010 (year 5) must exceed 2006 (year 1)
        due to the warming trend in the synthetic data."""
        ds = nc.Dataset(f'{RESULTS}/wsdi.nc', 'r')
        dvars = get_data_vars(ds)
        data = ds.variables[dvars[0]][:]
        ds.close()
        sum_first = float(np.nansum(data[0, ...]))
        sum_last = float(np.nansum(data[-1, ...]))
        assert sum_last >= sum_first, \
            f"WSDI 2010={sum_last:.0f} should >= 2006={sum_first:.0f}"


# =====================================================================
#  4. Monthly climatology — structural and DNA checks
# =====================================================================
class TestClimatology:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/ymon_clim.nc'), \
            "ymon_clim.nc missing"

    def test_12_months(self):
        ds = nc.Dataset(f'{RESULTS}/ymon_clim.nc', 'r')
        assert ds.dimensions['time'].size == 12, \
            f"Expected 12 months, got {ds.dimensions['time'].size}"
        ds.close()

    def test_dna_matches_independent(self):
        """Climatology must match independent ymonmean computation
        within 0.001 K (tight tolerance for seed-42 data)."""
        cdo_run(
            f"ymonmean -selyear,2001/2005 {RESULTS}/tasmax_regrid.nc "
            f"/tmp/_t_clim.nc"
        )
        ds_a = nc.Dataset(f'{RESULTS}/ymon_clim.nc', 'r')
        ds_r = nc.Dataset('/tmp/_t_clim.nc', 'r')
        av = get_data_vars(ds_a)
        rv = get_data_vars(ds_r)
        max_diff = float(np.max(np.abs(
            ds_a.variables[av[0]][:] - ds_r.variables[rv[0]][:]
        )))
        ds_a.close()
        ds_r.close()
        assert max_diff < 0.001, \
            f"Climatology deviates from reference by {max_diff:.6f} K"

    def test_dna_jan_fldmean_vs_raw(self):
        """January climatology field mean must match the mean of all
        January days from raw data 2001-2005 (within remapping tolerance)."""
        raw_jan = cdo_fldmean_val(
            f"{DATA}/tasmax_daily.nc",
            "-timmean -selmon,1 -selyear,2001/2005"
        )
        out_jan = cdo_fldmean_val(f"{RESULTS}/ymon_clim.nc", "-selmon,1")
        assert abs(raw_jan - out_jan) < 0.1, \
            f"Jan: raw={raw_jan:.4f}, clim={out_jan:.4f}"

    def test_dna_jul_fldmean_vs_raw(self):
        """July climatology field mean must match the mean of all
        July days from raw data 2001-2005."""
        raw_jul = cdo_fldmean_val(
            f"{DATA}/tasmax_daily.nc",
            "-timmean -selmon,7 -selyear,2001/2005"
        )
        out_jul = cdo_fldmean_val(f"{RESULTS}/ymon_clim.nc", "-selmon,7")
        assert abs(raw_jul - out_jul) < 0.1, \
            f"Jul: raw={raw_jul:.4f}, clim={out_jul:.4f}"

    def test_dna_seasonal_balance(self):
        """Global mean seasonal cycle should nearly cancel between
        hemispheres: |Jan - Jul| < 1.5 K for seed-42 data."""
        jan = cdo_fldmean_val(f"{RESULTS}/ymon_clim.nc", "-selmon,1")
        jul = cdo_fldmean_val(f"{RESULTS}/ymon_clim.nc", "-selmon,7")
        assert abs(jan - jul) < 1.5, \
            f"Seasonal imbalance: Jan={jan:.4f}, Jul={jul:.4f}"


# =====================================================================
#  5. Monthly anomalies — structural and DNA checks
# =====================================================================
class TestAnomalies:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/monthly_anomalies.nc'), \
            "monthly_anomalies.nc missing"

    def test_120_months(self):
        ds = nc.Dataset(f'{RESULTS}/monthly_anomalies.nc', 'r')
        assert ds.dimensions['time'].size == 120, \
            f"Expected 120 months, got {ds.dimensions['time'].size}"
        ds.close()

    def test_dna_ref_period_near_zero(self):
        """Mean anomaly over reference years 2001-2005 must be near zero
        (seed-42 specific tolerance)."""
        val = cdo_fldmean_val(
            f"{RESULTS}/monthly_anomalies.nc",
            "-timmean -selyear,2001/2005"
        )
        assert abs(val) < 0.15, \
            f"Ref-period mean anomaly = {val:.6f}, expected ~0"

    def test_dna_eval_reflects_trend(self):
        """Eval-period mean anomaly must reflect the 0.3 K/yr warming
        trend: expected ~1.5 K for seed-42 data."""
        val = cdo_fldmean_val(
            f"{RESULTS}/monthly_anomalies.nc",
            "-timmean -selyear,2006/2010"
        )
        assert 0.5 < val < 2.5, \
            f"Eval anomaly = {val:.4f}, expected ~1.5 K"

    def test_dna_annual_progression(self):
        """Mean anomaly must increase monotonically-ish over the decade
        (warming signal in seed-42 data)."""
        vals = []
        for yr in range(2001, 2011):
            v = cdo_fldmean_val(
                f"{RESULTS}/monthly_anomalies.nc",
                f"-timmean -selyear,{yr}"
            )
            vals.append(v)
        early = np.mean(vals[:3])
        late = np.mean(vals[-3:])
        assert late > early + 0.5, \
            f"Anomaly progression: early={early:.4f}, late={late:.4f}"

    def test_dna_matches_independent(self):
        """Monthly anomalies must match independent ymonsub computation
        from regridded data within 0.001 K."""
        cdo_run(
            f"ymonsub -monmean {RESULTS}/tasmax_regrid.nc "
            f"{RESULTS}/ymon_clim.nc /tmp/_t_anom.nc"
        )
        ds_a = nc.Dataset(f'{RESULTS}/monthly_anomalies.nc', 'r')
        ds_r = nc.Dataset('/tmp/_t_anom.nc', 'r')
        av = get_data_vars(ds_a)
        rv = get_data_vars(ds_r)
        max_diff = float(np.max(np.abs(
            ds_a.variables[av[0]][:] - ds_r.variables[rv[0]][:]
        )))
        ds_a.close()
        ds_r.close()
        assert max_diff < 0.001, \
            f"Anomaly deviates from reference by {max_diff:.6f} K"


# =====================================================================
#  6. Field mean of anomalies — structural and DNA checks
# =====================================================================
class TestFldmean:
    def test_exists(self):
        assert os.path.isfile(f'{RESULTS}/fldmean_anomalies.nc'), \
            "fldmean_anomalies.nc missing"

    def test_120_months(self):
        ds = nc.Dataset(f'{RESULTS}/fldmean_anomalies.nc', 'r')
        assert ds.dimensions['time'].size == 120, \
            f"Expected 120 months, got {ds.dimensions['time'].size}"
        ds.close()

    def test_single_point(self):
        ds = nc.Dataset(f'{RESULTS}/fldmean_anomalies.nc', 'r')
        dvars = get_data_vars(ds)
        spatial = int(np.prod(ds.variables[dvars[0]].shape[1:]))
        ds.close()
        assert spatial == 1, f"Expected gridsize=1, got {spatial}"

    def test_dna_exact_match(self):
        """Field mean values must match independently computed fldmean
        of the anomalies within 0.001 K."""
        cdo_run(
            f"fldmean {RESULTS}/monthly_anomalies.nc /tmp/_dna_fm.nc"
        )
        ds_a = nc.Dataset(f'{RESULTS}/fldmean_anomalies.nc', 'r')
        ds_r = nc.Dataset('/tmp/_dna_fm.nc', 'r')
        av = get_data_vars(ds_a)
        rv = get_data_vars(ds_r)
        max_diff = float(np.max(np.abs(
            ds_a.variables[av[0]][:] - ds_r.variables[rv[0]][:]
        )))
        ds_a.close()
        ds_r.close()
        assert max_diff < 0.001, \
            f"Field mean deviates by {max_diff:.6f}"

    def test_dna_overall_mean_positive(self):
        """Overall time-mean of field-mean anomalies must be positive
        (reflecting the warming trend in seed-42 data)."""
        val = cdo_fldmean_val(
            f"{RESULTS}/fldmean_anomalies.nc", "-timmean"
        )
        assert val > 0.3, \
            f"Overall anomaly mean = {val:.4f}, expected > 0.3 K"

    def test_dna_first_year_vs_last_year(self):
        """Field-mean anomaly in 2010 must exceed 2001 by >1.0 K."""
        v2001 = cdo_fldmean_val(
            f"{RESULTS}/fldmean_anomalies.nc",
            "-timmean -selyear,2001"
        )
        v2010 = cdo_fldmean_val(
            f"{RESULTS}/fldmean_anomalies.nc",
            "-timmean -selyear,2010"
        )
        assert v2010 > v2001 + 1.0, \
            f"2001={v2001:.4f}, 2010={v2010:.4f}, diff={v2010-v2001:.4f}"
