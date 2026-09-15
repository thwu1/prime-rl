#!/bin/bash
# Merge station metadata and observations into station.json
# Required by validate_runner.py for diagnostic validation.
#

META=/app/data/station_meta.json
OBS=/app/data/observations.json
OUT=/app/data/station.json

jq -n \
  --slurpfile meta "$META" \
  --slurpfile obs "$OBS" \
  '{
    name: $meta[0].name,
    elevation_m: $meta[0].position.elevation_m,
    latitude_deg: $meta[0].position.latitude_deg,
    longitude_deg: $meta[0].position.longitude_deg,
    anemometer_height_m: $meta[0].instrumentation.wind.height_m,
    daily: {
      doy: $obs[0].daily_obs.doy,
      date: $obs[0].daily_obs.date,
      tmin_fahrenheit: $obs[0].daily_obs.variables.tmin.value,
      tmax_fahrenheit: $obs[0].daily_obs.variables.tmax.value,
      tdew_fahrenheit: $obs[0].daily_obs.variables.tdew.value,
      ea_kpa: $obs[0].daily_obs.variables.ea.value,
      rs_langley: $obs[0].daily_obs.variables.rs.value,
      wind_speed_mph: $obs[0].daily_obs.variables.wind.value
    },
    hourly: {
      doy: $obs[0].hourly_obs.doy,
      time_utc: $obs[0].hourly_obs.time_utc,
      note: $obs[0].hourly_obs.note,
      tmean_fahrenheit: $obs[0].hourly_obs.variables.tmean.value,
      ea_kpa: $obs[0].hourly_obs.variables.ea.value,
      rs_langley: $obs[0].hourly_obs.variables.rs.value,
      wind_speed_mph: $obs[0].hourly_obs.variables.wind.value
    }
  }' > "$OUT"

echo "Generated $OUT"
