-- OMOP CDM v5.4 Schema (subset) for PostgreSQL
-- Tables created WITHOUT constraints to allow ETL data quality assessment
-- Constraints should be validated via DQD checks, not database enforcement

-- Vocabulary tables
CREATE TABLE concept (
    concept_id integer,
    concept_name varchar(255),
    domain_id varchar(20),
    vocabulary_id varchar(20),
    concept_class_id varchar(20),
    standard_concept varchar(1),
    concept_code varchar(50),
    valid_start_date date,
    valid_end_date date,
    invalid_reason varchar(1)
);

CREATE TABLE vocabulary (
    vocabulary_id varchar(20),
    vocabulary_name varchar(255),
    vocabulary_reference varchar(255),
    vocabulary_version varchar(255),
    vocabulary_concept_id integer
);

CREATE TABLE domain (
    domain_id varchar(20),
    domain_name varchar(255),
    domain_concept_id integer
);

CREATE TABLE concept_class (
    concept_class_id varchar(20),
    concept_class_name varchar(255),
    concept_class_concept_id integer
);

CREATE TABLE relationship (
    relationship_id varchar(20),
    relationship_name varchar(255),
    is_hierarchical varchar(1),
    defines_ancestry varchar(1),
    reverse_relationship_id varchar(20),
    relationship_concept_id integer
);

CREATE TABLE concept_relationship (
    concept_id_1 integer,
    concept_id_2 integer,
    relationship_id varchar(20),
    valid_start_date date,
    valid_end_date date,
    invalid_reason varchar(1)
);

CREATE TABLE concept_ancestor (
    ancestor_concept_id integer,
    descendant_concept_id integer,
    min_levels_of_separation integer,
    max_levels_of_separation integer
);

CREATE TABLE concept_synonym (
    concept_id integer,
    concept_synonym_name varchar(1000),
    language_concept_id integer
);

CREATE TABLE source_to_concept_map (
    source_code varchar(50),
    source_concept_id integer,
    source_vocabulary_id varchar(20),
    source_code_description varchar(255),
    target_concept_id integer,
    target_vocabulary_id varchar(20),
    valid_start_date date,
    valid_end_date date,
    invalid_reason varchar(1)
);

CREATE TABLE drug_strength (
    drug_concept_id integer,
    ingredient_concept_id integer,
    amount_value numeric,
    amount_unit_concept_id integer,
    numerator_value numeric,
    numerator_unit_concept_id integer,
    denominator_value numeric,
    denominator_unit_concept_id integer,
    box_size integer,
    valid_start_date date,
    valid_end_date date,
    invalid_reason varchar(1)
);

-- Metadata
CREATE TABLE cdm_source (
    cdm_source_name varchar(255),
    cdm_source_abbreviation varchar(25),
    cdm_holder varchar(255),
    source_description text,
    source_documentation_reference varchar(255),
    cdm_etl_reference varchar(255),
    source_release_date date,
    cdm_release_date date,
    cdm_version varchar(10),
    cdm_version_concept_id integer,
    vocabulary_version varchar(20)
);

-- Clinical tables
CREATE TABLE person (
    person_id integer,
    gender_concept_id integer,
    year_of_birth integer,
    month_of_birth integer,
    day_of_birth integer,
    birth_datetime timestamp,
    race_concept_id integer,
    ethnicity_concept_id integer,
    location_id integer,
    provider_id integer,
    care_site_id integer,
    person_source_value varchar(50),
    gender_source_value varchar(50),
    gender_source_concept_id integer,
    race_source_value varchar(50),
    race_source_concept_id integer,
    ethnicity_source_value varchar(50),
    ethnicity_source_concept_id integer
);

CREATE TABLE observation_period (
    observation_period_id integer,
    person_id integer,
    observation_period_start_date date,
    observation_period_end_date date,
    period_type_concept_id integer
);

CREATE TABLE visit_occurrence (
    visit_occurrence_id integer,
    person_id integer,
    visit_concept_id integer,
    visit_start_date date,
    visit_start_datetime timestamp,
    visit_end_date date,
    visit_end_datetime timestamp,
    visit_type_concept_id integer,
    provider_id integer,
    care_site_id integer,
    visit_source_value varchar(50),
    visit_source_concept_id integer,
    admitted_from_concept_id integer,
    admitted_from_source_value varchar(50),
    discharged_to_concept_id integer,
    discharged_to_source_value varchar(50),
    preceding_visit_occurrence_id integer
);

CREATE TABLE condition_occurrence (
    condition_occurrence_id integer,
    person_id integer,
    condition_concept_id integer,
    condition_start_date date,
    condition_start_datetime timestamp,
    condition_end_date date,
    condition_end_datetime timestamp,
    condition_type_concept_id integer,
    condition_status_concept_id integer,
    stop_reason varchar(20),
    provider_id integer,
    visit_occurrence_id integer,
    visit_detail_id integer,
    condition_source_value varchar(50),
    condition_source_concept_id integer,
    condition_status_source_value varchar(50)
);

CREATE TABLE drug_exposure (
    drug_exposure_id integer,
    person_id integer,
    drug_concept_id integer,
    drug_exposure_start_date date,
    drug_exposure_start_datetime timestamp,
    drug_exposure_end_date date,
    drug_exposure_end_datetime timestamp,
    verbatim_end_date date,
    drug_type_concept_id integer,
    stop_reason varchar(20),
    refills integer,
    quantity numeric,
    days_supply integer,
    sig text,
    route_concept_id integer,
    lot_number varchar(50),
    provider_id integer,
    visit_occurrence_id integer,
    visit_detail_id integer,
    drug_source_value varchar(50),
    drug_source_concept_id integer,
    route_source_value varchar(50),
    dose_unit_source_value varchar(50)
);

CREATE TABLE measurement (
    measurement_id integer,
    person_id integer,
    measurement_concept_id integer,
    measurement_date date,
    measurement_datetime timestamp,
    measurement_time varchar(10),
    measurement_type_concept_id integer,
    operator_concept_id integer,
    value_as_number numeric,
    value_as_concept_id integer,
    unit_concept_id integer,
    range_low numeric,
    range_high numeric,
    provider_id integer,
    visit_occurrence_id integer,
    visit_detail_id integer,
    measurement_source_value varchar(50),
    measurement_source_concept_id integer,
    unit_source_value varchar(50),
    unit_source_concept_id integer,
    value_source_value varchar(50),
    measurement_event_id integer,
    meas_event_field_concept_id integer
);

CREATE TABLE death (
    person_id integer,
    death_date date,
    death_datetime timestamp,
    death_type_concept_id integer,
    cause_concept_id integer,
    cause_source_value varchar(50),
    cause_source_concept_id integer
);

-- Derived tables (to be populated by the agent)
CREATE TABLE drug_era (
    drug_era_id integer,
    person_id integer,
    drug_concept_id integer,
    drug_era_start_date date,
    drug_era_end_date date,
    drug_exposure_count integer,
    gap_days integer
);

CREATE TABLE condition_era (
    condition_era_id integer,
    person_id integer,
    condition_concept_id integer,
    condition_era_start_date date,
    condition_era_end_date date,
    condition_occurrence_count integer
);
