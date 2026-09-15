Climate Model Output
====================
Coupled ocean-atmosphere model output in NetCDF-4 format.

File: climate_output.nc

Dimensions:
  time : 300
  lat  : 60
  lon  : 40

Variables:
  tas(time, lat, lon)      : Surface temperature anomaly [K]
                             Missing values indicate masked grid cells (land).
  toa_imbalance(time)      : Top-of-atmosphere net radiative imbalance [W/m^2]
  gmst_anomaly(time)       : Global-mean surface temperature anomaly [K]
  lon(lon)                 : Longitude [0, 360) degrees east
  lat(lat)                 : Latitude [-87, 87] degrees north
  time(time)               : Time step index [0, 299]

Grid: regular lon-lat, 9-degree zonal x ~3-degree meridional spacing.
Two rectangular land-mask regions set to missing.
