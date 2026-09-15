CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    family_name TEXT,
    given_name TEXT,
    birth_date TEXT,
    gender TEXT,
    managing_org_ref TEXT
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT,
    type_code TEXT,
    city TEXT,
    state TEXT
);

CREATE TABLE IF NOT EXISTS practitioners (
    id TEXT PRIMARY KEY,
    family_name TEXT,
    given_name TEXT,
    prefix TEXT,
    qualification_code TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    status TEXT,
    category_code TEXT,
    loinc_code TEXT,
    loinc_display TEXT,
    subject_ref TEXT,
    effective_date TEXT,
    value_number REAL,
    value_unit TEXT
);

CREATE TABLE IF NOT EXISTS medication_requests (
    id TEXT PRIMARY KEY,
    status TEXT,
    intent TEXT,
    subject_ref TEXT,
    medication_display TEXT
);

CREATE TABLE IF NOT EXISTS conditions (
    id TEXT PRIMARY KEY,
    clinical_status TEXT,
    verification_status TEXT,
    snomed_code TEXT,
    snomed_display TEXT,
    subject_ref TEXT
);
