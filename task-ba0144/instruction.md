A PostgreSQL database (`psql -U omop -d omop`) contains an OMOP CDM v5.4 schema loaded with synthetic patient data from a buggy ETL pipeline. The vocabulary tables (`concept`, `concept_ancestor`, `concept_relationship`, `vocabulary`, `domain`, `concept_class`) are correct. The clinical tables contain multiple data quality violations across the Kahn Framework categories: Conformance (relational integrity, value conformance), Completeness, and Plausibility (temporal, atemporal).

The database schema was deployed WITHOUT primary key, foreign key, or NOT NULL constraints -- as is common in real-world OMOP CDM ETL pipelines where data quality is assessed post-load via the DataQualityDashboard (DQD) rather than enforced at the database level.

## Objectives

1. **Identify and repair all data quality violations** in the clinical tables (`person`, `observation_period`, `visit_occurrence`, `condition_occurrence`, `drug_exposure`, `measurement`, `death`). Violations span:
   - Conformance/Relational: broken foreign keys to concept table, NULL values in spec-required fields, duplicate primary key values
   - Conformance/Value: non-standard concepts used where standard concepts are required (use `concept_relationship` with `relationship_id='Maps to'` to find correct mappings)
   - Completeness: persons without observation periods
   - Plausibility/Temporal: clinical events dated before birth, clinical events dated after death, exposure start dates after end dates
   - Plausibility/Atemporal: physically impossible measurement values

2. **Derive the `drug_era` table** following OMOP conventions:
   - Roll up `drug_concept_id` to ingredient level via `concept_ancestor` (ancestor with `concept_class_id='Ingredient'`)
   - Merge exposures to the same ingredient for the same person using a 30-day persistence window (exposures with a gap of ≤30 uncovered days are merged into one era)
   - Populate: `drug_era_id`, `person_id`, `drug_concept_id` (ingredient), `drug_era_start_date`, `drug_era_end_date`, `drug_exposure_count`, `gap_days` (total uncovered days within the era)

3. **Derive the `condition_era` table** following OMOP conventions:
   - Group by `person_id` and `condition_concept_id`; use `condition_end_date` (default to `condition_start_date` if NULL)
   - Merge conditions with ≤30-day gap
   - Populate: `condition_era_id`, `person_id`, `condition_concept_id`, `condition_era_start_date`, `condition_era_end_date`, `condition_occurrence_count`

4. **Write a DQD report** to `/app/dqd_report.json` documenting each violation found, its Kahn Framework category, affected table/field, number of affected rows, and the fix applied.