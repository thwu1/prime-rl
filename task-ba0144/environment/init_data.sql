-- OMOP CDM v5.4 Seed Data
-- Vocabulary tables contain correct reference data
-- Clinical tables contain DELIBERATE data quality violations for ETL debugging

-- ============================================================
-- VOCABULARY / REFERENCE DATA (correct - do not modify)
-- ============================================================

-- Domain
INSERT INTO domain VALUES ('Condition', 'Condition', 0);
INSERT INTO domain VALUES ('Drug', 'Drug', 0);
INSERT INTO domain VALUES ('Measurement', 'Measurement', 0);
INSERT INTO domain VALUES ('Visit', 'Visit', 0);
INSERT INTO domain VALUES ('Gender', 'Gender', 0);
INSERT INTO domain VALUES ('Race', 'Race', 0);
INSERT INTO domain VALUES ('Ethnicity', 'Ethnicity', 0);
INSERT INTO domain VALUES ('Type Concept', 'Type Concept', 0);
INSERT INTO domain VALUES ('Unit', 'Unit', 0);
INSERT INTO domain VALUES ('Metadata', 'Metadata', 0);
INSERT INTO domain VALUES ('Observation', 'Observation', 0);

-- Vocabulary
INSERT INTO vocabulary VALUES ('SNOMED', 'Systematic Nomenclature of Medicine - Clinical Terms', 'SNOMED-CT', '2023-09-01', 0);
INSERT INTO vocabulary VALUES ('RxNorm', 'RxNorm', 'NLM', '2023-09-05', 0);
INSERT INTO vocabulary VALUES ('LOINC', 'Logical Observation Identifiers Names and Codes', 'Regenstrief Institute', '2.76', 0);
INSERT INTO vocabulary VALUES ('Visit', 'OMOP Visit', 'OHDSI', 'v1', 0);
INSERT INTO vocabulary VALUES ('Gender', 'OMOP Gender', 'OHDSI', 'v1', 0);
INSERT INTO vocabulary VALUES ('Race', 'Race and Ethnicity Code Set', 'CDC', 'v1', 0);
INSERT INTO vocabulary VALUES ('Ethnicity', 'OMOP Ethnicity', 'OHDSI', 'v1', 0);
INSERT INTO vocabulary VALUES ('Type Concept', 'OMOP Type Concept', 'OHDSI', 'v2', 0);
INSERT INTO vocabulary VALUES ('UCUM', 'Unified Code for Units of Measure', 'Regenstrief Institute', '2.1', 0);
INSERT INTO vocabulary VALUES ('CDM', 'OMOP Common Data Model', 'OHDSI', 'v5.4', 0);
INSERT INTO vocabulary VALUES ('ICD10CM', 'International Classification of Diseases, 10th Revision, Clinical Modification', 'NLM', '2023', 0);
INSERT INTO vocabulary VALUES ('None', 'OMOP Standardized Vocabularies', 'OHDSI', 'v1', 0);

-- Concept Class
INSERT INTO concept_class VALUES ('Clinical Finding', 'Clinical Finding', 0);
INSERT INTO concept_class VALUES ('Clinical Drug', 'Clinical Drug', 0);
INSERT INTO concept_class VALUES ('Ingredient', 'Ingredient', 0);
INSERT INTO concept_class VALUES ('Clinical Observation', 'Clinical Observation', 0);
INSERT INTO concept_class VALUES ('Lab Test', 'Lab Test', 0);
INSERT INTO concept_class VALUES ('Visit', 'Visit', 0);
INSERT INTO concept_class VALUES ('Gender', 'Gender', 0);
INSERT INTO concept_class VALUES ('Race', 'Race', 0);
INSERT INTO concept_class VALUES ('Ethnicity', 'Ethnicity', 0);
INSERT INTO concept_class VALUES ('Type Concept', 'Type Concept', 0);
INSERT INTO concept_class VALUES ('Unit', 'Unit', 0);
INSERT INTO concept_class VALUES ('CDM', 'CDM', 0);
INSERT INTO concept_class VALUES ('4-char billing code', '4-char billing code', 0);
INSERT INTO concept_class VALUES ('Undefined', 'Undefined', 0);

-- Relationship
INSERT INTO relationship VALUES ('Maps to', 'Mapped to', '0', '0', 'Mapped from', 0);
INSERT INTO relationship VALUES ('Mapped from', 'Mapped from', '0', '0', 'Maps to', 0);
INSERT INTO relationship VALUES ('Is a', 'Is a', '1', '1', 'Subsumes', 0);
INSERT INTO relationship VALUES ('Subsumes', 'Subsumes', '1', '1', 'Is a', 0);

-- ============================================================
-- CONCEPT TABLE
-- ============================================================

-- No matching concept
INSERT INTO concept VALUES (0, 'No matching concept', 'Metadata', 'None', 'Undefined', NULL, 'No matching concept', '1970-01-01', '2099-12-31', NULL);

-- Gender
INSERT INTO concept VALUES (8507, 'MALE', 'Gender', 'Gender', 'Gender', 'S', 'M', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (8532, 'FEMALE', 'Gender', 'Gender', 'Gender', 'S', 'F', '1970-01-01', '2099-12-31', NULL);

-- Race
INSERT INTO concept VALUES (8516, 'Black or African American', 'Race', 'Race', 'Race', 'S', '3', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (8527, 'White', 'Race', 'Race', 'Race', 'S', '5', '1970-01-01', '2099-12-31', NULL);

-- Ethnicity
INSERT INTO concept VALUES (38003563, 'Hispanic or Latino', 'Ethnicity', 'Ethnicity', 'Ethnicity', 'S', 'Hispanic', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (38003564, 'Not Hispanic or Latino', 'Ethnicity', 'Ethnicity', 'Ethnicity', 'S', 'Not Hispanic', '1970-01-01', '2099-12-31', NULL);

-- Visit
INSERT INTO concept VALUES (9201, 'Inpatient Visit', 'Visit', 'Visit', 'Visit', 'S', 'IP', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (9202, 'Outpatient Visit', 'Visit', 'Visit', 'Visit', 'S', 'OP', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (9203, 'Emergency Room Visit', 'Visit', 'Visit', 'Visit', 'S', 'ER', '1970-01-01', '2099-12-31', NULL);

-- Type Concept
INSERT INTO concept VALUES (32817, 'EHR', 'Type Concept', 'Type Concept', 'Type Concept', 'S', 'OMOP generated', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (32810, 'Claim', 'Type Concept', 'Type Concept', 'Type Concept', 'S', 'Claim', '1970-01-01', '2099-12-31', NULL);

-- Conditions (SNOMED - Standard)
INSERT INTO concept VALUES (201826, 'Type 2 diabetes mellitus', 'Condition', 'SNOMED', 'Clinical Finding', 'S', '44054006', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (320128, 'Essential hypertension', 'Condition', 'SNOMED', 'Clinical Finding', 'S', '59621000', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (312327, 'Acute myocardial infarction', 'Condition', 'SNOMED', 'Clinical Finding', 'S', '57054005', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (255848, 'Pneumonia', 'Condition', 'SNOMED', 'Clinical Finding', 'S', '233604007', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (432867, 'Hyperlipidemia', 'Condition', 'SNOMED', 'Clinical Finding', 'S', '55822004', '1970-01-01', '2099-12-31', NULL);

-- Conditions (ICD10CM - Non-Standard)
INSERT INTO concept VALUES (44831230, 'Type 2 diabetes mellitus', 'Condition', 'ICD10CM', '4-char billing code', NULL, 'E11', '1970-01-01', '2099-12-31', NULL);

-- Drug Products (RxNorm - Standard)
INSERT INTO concept VALUES (40165015, 'lisinopril 10 MG Oral Tablet', 'Drug', 'RxNorm', 'Clinical Drug', 'S', '314076', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (40165016, 'metformin 500 MG Oral Tablet', 'Drug', 'RxNorm', 'Clinical Drug', 'S', '861007', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (40165017, 'atorvastatin 20 MG Oral Tablet', 'Drug', 'RxNorm', 'Clinical Drug', 'S', '259255', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (40165018, 'amlodipine 5 MG Oral Tablet', 'Drug', 'RxNorm', 'Clinical Drug', 'S', '197361', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (40165019, 'hydrochlorothiazide 25 MG Oral Tablet', 'Drug', 'RxNorm', 'Clinical Drug', 'S', '310798', '1970-01-01', '2099-12-31', NULL);

-- Drug Ingredients (RxNorm - Standard)
INSERT INTO concept VALUES (1335471, 'lisinopril', 'Drug', 'RxNorm', 'Ingredient', 'S', '29046', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (1503297, 'metformin', 'Drug', 'RxNorm', 'Ingredient', 'S', '6809', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (1545958, 'atorvastatin', 'Drug', 'RxNorm', 'Ingredient', 'S', '83367', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (1332418, 'amlodipine', 'Drug', 'RxNorm', 'Ingredient', 'S', '17767', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (974166, 'hydrochlorothiazide', 'Drug', 'RxNorm', 'Ingredient', 'S', '5487', '1970-01-01', '2099-12-31', NULL);

-- Measurements (LOINC - Standard)
INSERT INTO concept VALUES (3004249, 'Systolic blood pressure', 'Measurement', 'LOINC', 'Clinical Observation', 'S', '8480-6', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (3012888, 'Diastolic blood pressure', 'Measurement', 'LOINC', 'Clinical Observation', 'S', '8462-4', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (3038553, 'Body mass index', 'Measurement', 'LOINC', 'Clinical Observation', 'S', '39156-5', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (3016723, 'Creatinine in Serum or Plasma', 'Measurement', 'LOINC', 'Lab Test', 'S', '2160-0', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (3004501, 'Glucose in Serum or Plasma', 'Measurement', 'LOINC', 'Lab Test', 'S', '2345-7', '1970-01-01', '2099-12-31', NULL);

-- Units (UCUM - Standard)
INSERT INTO concept VALUES (8876, 'millimeter mercury column', 'Unit', 'UCUM', 'Unit', 'S', 'mm[Hg]', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (9529, 'kilogram per square meter', 'Unit', 'UCUM', 'Unit', 'S', 'kg/m2', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept VALUES (8840, 'milligram per deciliter', 'Unit', 'UCUM', 'Unit', 'S', 'mg/dL', '1970-01-01', '2099-12-31', NULL);

-- CDM Version
INSERT INTO concept VALUES (756265, 'OMOP CDM Version 5.4', 'Metadata', 'CDM', 'CDM', 'S', 'CDM v5.4', '1970-01-01', '2099-12-31', NULL);

-- ============================================================
-- CONCEPT RELATIONSHIP (Maps to / Mapped from)
-- ============================================================
INSERT INTO concept_relationship VALUES (44831230, 201826, 'Maps to', '1970-01-01', '2099-12-31', NULL);
INSERT INTO concept_relationship VALUES (201826, 44831230, 'Mapped from', '1970-01-01', '2099-12-31', NULL);

-- ============================================================
-- CONCEPT ANCESTOR (Drug Product -> Ingredient hierarchy)
-- ============================================================
-- Product to Ingredient ancestors
INSERT INTO concept_ancestor VALUES (1335471, 40165015, 1, 1);
INSERT INTO concept_ancestor VALUES (1503297, 40165016, 1, 1);
INSERT INTO concept_ancestor VALUES (1545958, 40165017, 1, 1);
INSERT INTO concept_ancestor VALUES (1332418, 40165018, 1, 1);
INSERT INTO concept_ancestor VALUES (974166, 40165019, 1, 1);
-- Self-ancestors for drug products
INSERT INTO concept_ancestor VALUES (40165015, 40165015, 0, 0);
INSERT INTO concept_ancestor VALUES (40165016, 40165016, 0, 0);
INSERT INTO concept_ancestor VALUES (40165017, 40165017, 0, 0);
INSERT INTO concept_ancestor VALUES (40165018, 40165018, 0, 0);
INSERT INTO concept_ancestor VALUES (40165019, 40165019, 0, 0);
-- Self-ancestors for ingredients
INSERT INTO concept_ancestor VALUES (1335471, 1335471, 0, 0);
INSERT INTO concept_ancestor VALUES (1503297, 1503297, 0, 0);
INSERT INTO concept_ancestor VALUES (1545958, 1545958, 0, 0);
INSERT INTO concept_ancestor VALUES (1332418, 1332418, 0, 0);
INSERT INTO concept_ancestor VALUES (974166, 974166, 0, 0);

-- ============================================================
-- CDM SOURCE METADATA
-- ============================================================
INSERT INTO cdm_source VALUES (
    'Synthetic CDM', 'SYNTH', 'Synthetic',
    'Synthetic patient data loaded via a buggy ETL pipeline for data quality assessment',
    NULL, NULL, '2024-01-01', '2024-01-01', '5.4', 756265, 'v5.0 2024-01-01'
);

-- ============================================================
-- CLINICAL DATA (contains deliberate data quality violations)
-- ============================================================

-- Person (10 patients)
INSERT INTO person VALUES (1, 8507, 1960, 1, 15, '1960-01-15', 8527, 38003564, NULL, NULL, NULL, 'P001', 'M', NULL, 'White', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (2, 8532, 1975, 3, 22, '1975-03-22', 8516, 38003564, NULL, NULL, NULL, 'P002', 'F', NULL, 'Black', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (3, 8507, 1950, 7, 10, '1950-07-10', 8527, 38003563, NULL, NULL, NULL, 'P003', 'M', NULL, 'White', NULL, 'Hispanic', NULL);
INSERT INTO person VALUES (4, 8532, 1985, 11, 5, '1985-11-05', 8527, 38003564, NULL, NULL, NULL, 'P004', 'F', NULL, 'White', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (5, 8507, 1945, 5, 20, '1945-05-20', 8516, 38003564, NULL, NULL, NULL, 'P005', 'M', NULL, 'Black', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (6, 8532, 1990, 9, 1, '1990-09-01', 8527, 38003564, NULL, NULL, NULL, 'P006', 'F', NULL, 'White', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (7, 8507, 1955, 2, 28, '1955-02-28', 8527, 38003563, NULL, NULL, NULL, 'P007', 'M', NULL, 'White', NULL, 'Hispanic', NULL);
INSERT INTO person VALUES (8, 8532, 1970, 12, 15, '1970-12-15', 8516, 38003564, NULL, NULL, NULL, 'P008', 'F', NULL, 'Black', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (9, 8507, 1965, 4, 8, '1965-04-08', 8527, 38003564, NULL, NULL, NULL, 'P009', 'M', NULL, 'White', NULL, 'Not Hispanic', NULL);
INSERT INTO person VALUES (10, 8532, 1980, 8, 17, '1980-08-17', 8527, 38003563, NULL, NULL, NULL, 'P010', 'F', NULL, 'White', NULL, 'Hispanic', NULL);

-- Observation Period
-- BUG: person_id=7 has NULL observation_period_end_date (violates NOT NULL requirement)
-- BUG: person_id=8 has NO observation_period record (completeness violation)
INSERT INTO observation_period VALUES (1, 1, '2020-01-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (2, 2, '2019-01-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (3, 3, '2018-01-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (4, 4, '2020-06-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (5, 5, '2015-01-01', '2023-06-15', 32817);
INSERT INTO observation_period VALUES (6, 6, '2021-01-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (7, 7, '2019-06-01', NULL, 32817);
INSERT INTO observation_period VALUES (8, 9, '2020-01-01', '2024-12-31', 32817);
INSERT INTO observation_period VALUES (9, 10, '2019-01-01', '2024-12-31', 32817);

-- Death
INSERT INTO death VALUES (5, '2023-06-15', '2023-06-15 00:00:00', 32817, NULL, NULL, NULL);

-- Visit Occurrence
-- BUG: visit_occurrence_id=5 appears TWICE (duplicate primary key violation)
INSERT INTO visit_occurrence VALUES (1, 1, 9202, '2022-03-15', '2022-03-15 09:00:00', '2022-03-15', '2022-03-15 17:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (2, 1, 9202, '2022-09-20', '2022-09-20 09:00:00', '2022-09-20', '2022-09-20 17:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (3, 2, 9202, '2022-04-10', '2022-04-10 10:00:00', '2022-04-10', '2022-04-10 11:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (4, 3, 9201, '2022-05-01', '2022-05-01 00:00:00', '2022-05-05', '2022-05-05 12:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (5, 4, 9202, '2022-07-15', '2022-07-15 14:00:00', '2022-07-15', '2022-07-15 15:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (5, 4, 9203, '2022-08-20', '2022-08-20 08:00:00', '2022-08-20', '2022-08-20 16:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (6, 5, 9201, '2023-06-10', '2023-06-10 00:00:00', '2023-06-15', '2023-06-15 23:59:59', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (7, 6, 9202, '2023-01-20', '2023-01-20 09:00:00', '2023-01-20', '2023-01-20 10:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (8, 7, 9202, '2022-11-10', '2022-11-10 11:00:00', '2022-11-10', '2022-11-10 12:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (9, 9, 9202, '2022-06-15', '2022-06-15 09:00:00', '2022-06-15', '2022-06-15 10:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (10, 10, 9202, '2023-02-28', '2023-02-28 14:00:00', '2023-02-28', '2023-02-28 15:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO visit_occurrence VALUES (11, 8, 9202, '2021-03-15', '2021-03-15 10:00:00', '2021-03-15', '2021-03-15 11:00:00', 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

-- Condition Occurrence
-- BUG: condition_occurrence_id=5 uses non-standard concept_id 44831230 (ICD10CM) instead of standard SNOMED
-- BUG: condition_occurrence_id=11 has date 1985-06-15 for person_id=6 who was born in 1990 (before birth)
INSERT INTO condition_occurrence VALUES (1, 1, 201826, '2022-03-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E11.9', NULL, NULL);
INSERT INTO condition_occurrence VALUES (2, 1, 320128, '2022-03-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'I10', NULL, NULL);
INSERT INTO condition_occurrence VALUES (3, 2, 432867, '2022-04-10', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E78.5', NULL, NULL);
INSERT INTO condition_occurrence VALUES (4, 3, 312327, '2022-05-01', NULL, '2022-05-05', NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'I21.9', NULL, NULL);
INSERT INTO condition_occurrence VALUES (5, 4, 44831230, '2022-07-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E11', NULL, NULL);
INSERT INTO condition_occurrence VALUES (6, 5, 255848, '2023-06-10', NULL, '2023-06-15', NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'J18.9', NULL, NULL);
INSERT INTO condition_occurrence VALUES (7, 6, 201826, '2023-01-20', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E11.65', NULL, NULL);
INSERT INTO condition_occurrence VALUES (8, 7, 320128, '2022-11-10', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'I10', NULL, NULL);
INSERT INTO condition_occurrence VALUES (9, 9, 201826, '2022-06-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E11.9', NULL, NULL);
INSERT INTO condition_occurrence VALUES (10, 10, 320128, '2023-02-28', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'I10', NULL, NULL);
INSERT INTO condition_occurrence VALUES (11, 6, 320128, '1985-06-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'I10', NULL, NULL);
INSERT INTO condition_occurrence VALUES (12, 8, 432867, '2021-03-15', NULL, NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, 'E78.5', NULL, NULL);

-- Drug Exposure
-- BUG: drug_exposure_id=6 references drug_concept_id=99999 which does not exist in concept table (broken FK)
-- BUG: drug_exposure_id=9 has start_date (2022-10-01) AFTER end_date (2022-06-01)
INSERT INTO drug_exposure VALUES (1, 1, 40165015, '2022-03-15', NULL, '2022-06-15', NULL, NULL, 32817, NULL, NULL, NULL, 93, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (2, 1, 40165016, '2022-03-15', NULL, '2022-09-15', NULL, NULL, 32817, NULL, NULL, NULL, 185, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (3, 1, 40165015, '2022-07-01', NULL, '2022-12-31', NULL, NULL, 32817, NULL, NULL, NULL, 184, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (4, 2, 40165017, '2022-04-10', NULL, '2022-10-10', NULL, NULL, 32817, NULL, NULL, NULL, 183, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (5, 3, 40165018, '2022-05-01', NULL, '2022-05-05', NULL, NULL, 32817, NULL, NULL, NULL, 5, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (6, 4, 99999, '2022-07-15', NULL, '2022-08-15', NULL, NULL, 32817, NULL, NULL, NULL, 31, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (7, 5, 40165019, '2023-06-01', NULL, '2023-06-15', NULL, NULL, 32817, NULL, NULL, NULL, 15, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (8, 6, 0, '2023-01-20', NULL, '2023-07-20', NULL, NULL, 32817, NULL, NULL, NULL, 182, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (9, 9, 40165015, '2022-10-01', NULL, '2022-06-01', NULL, NULL, 32817, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (10, 10, 40165017, '2023-02-28', NULL, '2023-08-28', NULL, NULL, 32817, NULL, NULL, NULL, 182, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (11, 1, 40165015, '2023-02-01', NULL, '2023-08-01', NULL, NULL, 32817, NULL, NULL, NULL, 182, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (12, 1, 40165016, '2022-10-01', NULL, '2023-03-31', NULL, NULL, 32817, NULL, NULL, NULL, 182, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO drug_exposure VALUES (13, 8, 40165017, '2021-03-15', NULL, '2021-09-15', NULL, NULL, 32817, NULL, NULL, NULL, 185, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

-- Measurement
-- BUG: measurement_id=3 has negative BMI value (-25.5) which is physically impossible
-- BUG: measurement_id=5 has date 2023-07-01 for person_id=5 who died on 2023-06-15 (after death)
INSERT INTO measurement VALUES (1, 1, 3004249, '2022-03-15', NULL, NULL, 32817, NULL, 130.0, NULL, 8876, NULL, NULL, NULL, NULL, NULL, '8480-6', NULL, 'mm[Hg]', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (2, 1, 3012888, '2022-03-15', NULL, NULL, 32817, NULL, 85.0, NULL, 8876, NULL, NULL, NULL, NULL, NULL, '8462-4', NULL, 'mm[Hg]', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (3, 2, 3038553, '2022-04-10', NULL, NULL, 32817, NULL, -25.5, NULL, 9529, NULL, NULL, NULL, NULL, NULL, '39156-5', NULL, 'kg/m2', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (4, 3, 3016723, '2022-05-01', NULL, NULL, 32817, NULL, 1.2, NULL, 8840, NULL, NULL, NULL, NULL, NULL, '2160-0', NULL, 'mg/dL', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (5, 5, 3004249, '2023-07-01', NULL, NULL, 32817, NULL, 110.0, NULL, 8876, NULL, NULL, NULL, NULL, NULL, '8480-6', NULL, 'mm[Hg]', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (6, 4, 3004501, '2022-07-15', NULL, NULL, 32817, NULL, 105.0, NULL, 8840, NULL, NULL, NULL, NULL, NULL, '2345-7', NULL, 'mg/dL', NULL, NULL, NULL, NULL);
INSERT INTO measurement VALUES (7, 9, 3038553, '2022-06-15', NULL, NULL, 32817, NULL, 28.3, NULL, 9529, NULL, NULL, NULL, NULL, NULL, '39156-5', NULL, 'kg/m2', NULL, NULL, NULL, NULL);
