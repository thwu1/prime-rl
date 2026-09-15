`/app/cffwis.py` implements the Canadian Forest Fire Weather Index System but contains bugs in its numerical computations. The correct equations are documented in `/app/reference_equations.md`.

`/app/weather_data.csv` contains 30 years (1990–2019) of daily noon weather observations for 5 stations at latitudes 45°N, 55°N, 65°N, 10°N, and 35°S. `/app/fire_events.csv` contains corresponding daily fire occurrence records.

Fix all bugs in `/app/cffwis.py` and produce:

**`/app/fwi_output.csv`** — Daily CFFWIS indices for all stations and days. Columns: `date, station_id, FFMC, DMC, DC, ISI, BUI, FWI, DSR, season_mask`. Non-season values should be empty.

**`/app/results.json`** — Per-station extreme value analysis and fire danger calibration:
```json
{"stations": {"<id>": {
  "gev_params": {"shape": <xi>, "location": <mu>, "scale": <sigma>},
  "return_levels": {"20": <val>, "50": <val>, "100": <val>},
  "danger_threshold": <fwi_value>,
  "verification": {"hss": <val>, "pod": <val>, "far": <val>, "csi": <val>}
}}}
```

For each station: fit an extreme value distribution to annual peak fire weather intensity during the fire season, compute return levels for 20-, 50-, and 100-year return periods, determine the FWI threshold that best discriminates fire-prone conditions against the historical fire record, and report standard forecast verification scores at that threshold.