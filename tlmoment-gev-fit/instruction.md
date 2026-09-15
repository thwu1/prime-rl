`/data/` contains annual maximum measurements from five monitoring stations (`station_A.csv` through `station_E.csv`), one value per line, no header.

Produce an extreme value analysis for each station and write results to `/app/report.json`:

```json
{
  "station_A": {
    "family": "frechet" | "gumbel" | "weibull",
    "params": {"xi": ..., "sigma": ..., "mu": ...},
    "return_levels": {"T100": ..., "T500": ...},
    "contaminated": true | false,
    "suspect_fraction": 0.0
  },
  ...same for all five stations...
}
```

- `family`: GEV distribution subtype — `"frechet"` (xi > 0), `"gumbel"` (xi ≈ 0), or `"weibull"` (xi < 0)
- `params`: GEV parameters (shape xi, scale sigma > 0, location mu) best characterizing the station's underlying extreme value distribution
- `return_levels`: 100-year and 500-year return level estimates derived from the fitted GEV
- `contaminated`: whether the data contains observations inconsistent with the bulk extreme value distribution
- `suspect_fraction`: approximate fraction of such anomalous observations (0.0 if none)

Do not use pre-built extreme value or L-moment libraries (`lmo`, `lmoments3`, `scipy.stats.genextreme`, `pyextremes`, etc.). General-purpose numerical tools (`numpy`, `scipy.optimize`) are permitted.