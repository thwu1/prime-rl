The `/app/` directory contains a Maven-based Java project and a data-processing pipeline intended to compute ISDA CDS Standard Model analytics for three single-name credit default swap trades.

**Project layout:**
- `/app/pom.xml` — Maven build configuration
- `/app/pipeline.sh` — orchestration script: data preprocessing, Maven compilation, execution
- `/app/src/main/java/cds/CdsPricer.java` — main class (pricing logic unimplemented)
- `/app/src/main/java/cds/DataLoader.java` — market data file parser
- `/app/src/main/java/cds/Trade.java` — trade specification
- `/app/data/yield_curve.b64` — base64-encoded pre-calibrated ISDA yield/discount curve (ACT/365F)
- `/app/data/credit_curve.csv` — pre-calibrated ISDA credit/survival curve
- `/app/data/trades_raw.json` — trade definitions and model conventions in raw market-data feed format

The pipeline, Maven configuration, data loader, and `jq` transformation in `pipeline.sh` all contain defects. The raw market-data feed in `trades_raw.json` uses different field-naming conventions, nesting, and unit scales than what the Java data loader expects. The yield curve must be decoded from base64 before use.

**Required output** `/app/results.json` — flat JSON object with keys:
`nextday_protection_leg`, `nextday_dirty_annuity`, `nextday_clean_pv`,
`before_protection_leg`, `before_dirty_annuity`, `before_clean_pv`,
`after_protection_leg`, `after_dirty_annuity`, `after_clean_pv`

Protection leg and dirty risky annuity values are per-unit-notional. Clean PV values incorporate trade direction, notional, coupon rate, and accrued premium adjustment at step-in.

**Tolerances:** per-unit values ±1e-9 absolute; PV values ±10.0 absolute.

**Execution:** `cd /app && bash pipeline.sh`
