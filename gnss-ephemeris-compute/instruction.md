Build `/app/gnss_pipeline.py` with subcommands `process`, `convert`, `export`, `validate`.

**process**

```
python3 /app/gnss_pipeline.py process \
  --nav /app/data/mixed.25n /app/data/gps_v2.99n \
  --db /app/output/gnss.db --report /app/output/report.json
```

Accept RINEX navigation files (v2.11 or v3.05), auto-detecting version from header. Parse GPS (`G`) and Galileo (`E`) broadcast ephemeris. Deduplicate by (satellite, Toe). For each unique pair, compute WGS-84 ECEF position and clock/relativistic corrections at Toe, Toe+300s, Toe+600s.

SQLite schema for `/app/output/gnss.db`:

```sql
CREATE TABLE positions (
  satellite TEXT NOT NULL, gps_week INTEGER NOT NULL,
  tow REAL NOT NULL, x_m REAL NOT NULL, y_m REAL NOT NULL, z_m REAL NOT NULL,
  clock_correction_s REAL NOT NULL, relativistic_correction_s REAL NOT NULL,
  orbit_radius_m REAL NOT NULL, anomaly_flag INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (satellite, tow)
);
```

`gps_week`: GPS week number derived from the RINEX epoch date. `orbit_radius_m`: position vector Euclidean norm. `anomaly_flag=1` when radius outside GPS 24000--28000 km or Galileo 27000--32000 km.

Report `/app/output/report.json`: `satellites_processed` (sorted), `total_positions`, `anomalous_satellites` (sorted, any flagged position), `rms_radius_deviation` (per non-anomalous satellite, RMS of radius minus nominal in meters; nominals: GPS 26560 km, Galileo 29600 km).

**convert**

```
python3 /app/gnss_pipeline.py convert \
  --input /app/data/gps_v2.99n --output /app/output/converted.25n
```

Convert RINEX 2.11 GPS navigation to valid 3.05 format. Output must be parseable by `process` producing identical positions (within tolerance). ION ALPHA/BETA become GPSA/GPSB IONOSPHERIC CORR; DELTA-UTC becomes GPUT TIME SYSTEM CORR. Header labels occupy columns 61--80.

**export**

```
python3 /app/gnss_pipeline.py export \
  --db /app/output/gnss.db --sp3 /app/output/orbits.sp3
```

Export non-anomalous positions to SP3c format. Required header: `#cP` version line (start epoch, epoch count, `ORBIT`, `WGS84`, `BCT`, `GNSS`); `##` line with GPS week, seconds-of-week, epoch interval 300.0, Modified Julian Day, fractional day; five `+` lines (satellite count and IDs padded to 17 per line with `  0`); five `++` accuracy exponent lines; two `%c` (first must specify time system `GPS`), two `%f`, two `%i`; four `/*` comment lines. Per epoch: `*` header with calendar date (`YYYY MM DD HH MM SS.SSSSSSSS`), then `P`-prefixed position lines (3-char satellite ID, XYZ in km as F14.6, clock correction in microseconds as F14.6). Terminate with `EOF`. Derive calendar dates from GPS epoch (1980-01-06) plus GPS week and TOW.

**validate**

```
python3 /app/gnss_pipeline.py validate \
  --db /app/output/gnss.db --sp3 /app/output/orbits.sp3 \
  --output /app/output/validation.json
```

Cross-validate database against SP3 file. For each non-anomalous satellite: verify SP3 positions match database within 0.001 km; compute inter-epoch velocity (km/s) from consecutive positions, flag `velocity_anomaly` if any outside 2.0--5.0 km/s; compute clock drift rate (delta clock_correction_s / delta t), flag `clock_drift_anomaly` if |rate| > 1e-6 s/s. Output:

```json
{"satellites": {"G06": {"sp3_match": true, "max_position_error_km": 0.0,
  "velocities_km_s": [...], "velocity_anomaly": false,
  "clock_drift_rates": [...], "clock_drift_anomaly": false}, ...},
 "overall_pass": true}
```

**Constants**: GPS mu = 3.986005e14 m^3/s^2, Galileo mu = 3.986004418e14 m^3/s^2, omega_e = 7.2921151467e-5 rad/s, c = 299792458.0 m/s.

**Tolerances**: positions within 0.01 m, clock and relativistic corrections within 1e-12 s.
