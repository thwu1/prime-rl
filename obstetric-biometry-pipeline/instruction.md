The R pipeline in `/app/` processes obstetric ultrasound data through two analysis modules:

- `/app/fetal_biometry.R` — Estimated fetal weight (EFW), gestational age dating, growth percentile classification, and published reference chart auditing
- `/app/doppler_surveillance.R` — Doppler waveform index computation, cerebroplacental ratio (CPR), amniotic fluid index (AFI) percentile assessment, and umbilical artery PI z-scoring against published reference norms

The orchestrator `/app/run_pipeline.R` reads `/app/patients.csv`, processes each patient through both modules, and writes `/app/results.json`.

The pipeline currently produces incorrect and incomplete clinical results due to computational bugs across both modules, cross-module coupling errors, and unfinished stub functions. Fix all errors and complete all stubs so that `Rscript /app/run_pipeline.R` produces a correct `/app/results.json`.

The output JSON must contain for each patient:

- `efw`: map of EFW estimates in grams (rounded to 1 decimal) keyed by formula variant, including only variants whose required inputs are present
- `composite_ga_weeks`: composite gestational age in weeks (rounded to 2 decimals)
- `growth_percentile`: percentile (rounded to 2 decimals) from the best available EFW and known GA
- `classification`: `SGA` (< 10), `AGA` (10–90), or `LGA` (> 90)
- `doppler`: object with `ua_sd`, `ua_ri`, `ua_pi`, `mca_pi` (rounded to 3 decimals), `cpr` (rounded to 3), boolean flags `aedf` and `redf`, and `ua_pi_zscore` (rounded to 2 decimals — z-score of observed UA PI against gestational-age-specific reference norms, valid for 20–42 weeks); or `null` when UA Doppler data is absent
- `afi`: object with `value_mm`, `percentile` (rounded to 2 decimals), `classification` (`oligohydramnios`, `polyhydramnios`, or `normal`); or `null` when AFI data is absent

Edge-case requirements:

- Absent end-diastolic flow (EDV = 0): `ua_sd` must be `null`, `ua_ri` must equal 1.0, `aedf` must be `true`; pulsatility index and z-score remain computable
- Reversed end-diastolic flow (EDV < 0): `ua_sd` must be `null`, `redf` must be `true`; resistance and pulsatility indices remain computable
- Missing biometric parameters must not cause NA propagation into composite estimates
- CPR requires both UA and MCA pulsatility indices; must be `null` when either is unavailable
- `ua_pi_zscore` must be `null` when UA PI is unavailable or gestational age is outside the reference range (20–42 weeks)
- AFI percentile must return `null` for gestational ages outside the reference range (16–42 weeks); non-integer weeks must be handled via interpolation
- AFI classification: `oligohydramnios` (< 5th percentile), `polyhydramnios` (> 95th percentile), `normal` otherwise
- Some bugs interact across modules — fixing certain outputs requires first correcting upstream parameters they depend on

The JSON must also contain `chart_audit` with `total_errors` equal to `0`.
