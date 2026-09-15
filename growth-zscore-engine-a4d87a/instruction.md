The growth assessment engine at `/app/growth_engine.R` produces incorrect and incomplete results. When invoked as:

    Rscript /app/growth_engine.R /app/data input.json output.json

it must read a JSON array of patients and write correct assessment results to the output file.

**Input**: JSON array of patient objects with `id` (string), `ga_birth` (gestational age at birth in weeks), `sex` (`"m"` or `"f"`), and `measurements` (array of objects with `pma_weeks`, `measure_type`, `value`).

**Output**: JSON array where each patient object contains:

- `patient_id`, `ga_birth`, `sex`
- `assessments`: array of objects with `value`, `measure_type`, `sex`, `pma_weeks`, `z_score`, `percentile`, `chart_used`
- `crossings`: percentile crossing events between consecutive same-type measurements across standard lines (3rd, 10th, 25th, 50th, 75th, 90th, 97th), each with `measure_type`, `from_pma`, `to_pma`, `percentile_crossed`, `direction` (`"up"` or `"down"`)
- `velocities`: growth velocity for each consecutive same-type measurement pair, with `measure_type`, `from_pma`, `to_pma`, `delta_z`, `delta_z_per_week`, `flag` (`"rapid_loss"` if delta_z_per_week < −0.1, `"rapid_gain"` if > 0.1, `"normal"` otherwise)

**Chart routing**: Preterm infants (`ga_birth` < 37) at PMA ≤ 50 weeks use Fenton 2013 data from `/app/data/fenton2013.csv`. Within that range, PMA 40–50 requires blending between Fenton and WHO z-scores. Report `chart_used` as `"fenton_2013"` (PMA < 40), `"fenton_who_blend"` (40 ≤ PMA ≤ 50, preterm), or `"who_2006_infant"` (all other cases).

**Correctness**: Z-scores and percentiles must be numerically accurate for both sexes against the reference data. The existing engine contains multiple computational errors that must be identified and corrected.

**Reference data**: `/app/data/charts_long.csv` (WHO 2006 infant charts), `/app/data/fenton2013.csv` (Fenton 2013 preterm charts). Both CSVs have columns: chart, age, age_units, gender, measure, measure_units, L, M, S.

**Tolerances**: z-scores ±0.01, percentiles ±0.005.
