An NCCSV file at `/app/data/ocean_profiles.nccsv` contains CTD profile data from three fixed mooring stations in the California Current System. Each station has multiple vertical casts at different times, with measurements at varying pressure levels -- a **timeSeriesProfile** feature type (CF-1.8 H.5). Variables include station identifier, coordinates, profile identifier, time, pressure (dbar), temperature (deg C), and salinity (PSU), with some NaN-encoded missing values.

Produce two output files:

**`/app/output/profiles.nc`** -- CF-1.8 NetCDF-4 with **timeSeriesProfile** DSG using the ragged array representation: station coordinates on a `station` dimension, profile metadata on a `profile` dimension linked via an index variable with `instance_dimension="station"`, observations on an `obs` dimension with per-profile counts via a variable carrying `sample_dimension="obs"`. Preserve the source pressure and also compute a **depth** variable from pressure and station latitude using the UNESCO 1983 equation (Fofonoff & Millard, Technical Papers in Marine Science No. 44) with `standard_name="depth"`, `units="m"`, `positive="down"`, `axis="Z"`.

Implement two QARTOD quality control tests on temperature, encoded as separate variables linked to temperature via the CF `ancillary_variables` attribute:

- **Gross range** (`temperature_gross_range_qc`): fail(4) if T < -2.5 or T > 40.0; suspect(3) if T < 1.0 or T > 32.0; pass(1) otherwise; missing(9) for NaN.
- **Spike test** (`temperature_spike_qc`): for interior point n in each profile, spike = |T[n] - (T[n-1] + T[n+1]) / 2|; fail(4) if spike > 6.0, suspect(3) if spike > 2.0, pass(1) otherwise. Endpoints and points adjacent to NaN: not_evaluated(2). NaN data: missing(9).

Both QC variables need `flag_values` and `flag_meanings`. The station identifier must carry `cf_role="timeseries_id"` and the profile identifier `cf_role="profile_id"`. Time must be numeric, encoded relative to a 1970 epoch. Data variables require a `coordinates` attribute. `ncdump` and `ncgen` are available.

**`/app/output/erddap_config.xml`** -- ERDDAP `datasets.xml` fragment as `EDDTableFromNcCFFiles` with `cdm_data_type=TimeSeriesProfile`, `cdm_timeseries_variables` (station ID, lat, lon), `cdm_profile_variables` (profile ID, time), `featureType`, `reloadEveryNMinutes`, and `dataVariable` blocks for all variables.