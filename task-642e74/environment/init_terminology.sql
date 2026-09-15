-- FHIR Terminology Service Cache
-- Value Set expansions exported from VSAC for CMS165v14 and dependent libraries
-- Schema models the FHIR ValueSet resource expansion structure

CREATE TABLE coding_systems (
    system_id INTEGER PRIMARY KEY,
    uri TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

INSERT INTO coding_systems VALUES (1, 'http://hl7.org/fhir/sid/icd-10-cm', 'ICD-10-CM');
INSERT INTO coding_systems VALUES (2, 'http://www.ama-assn.org/go/cpt', 'CPT');
INSERT INTO coding_systems VALUES (3, 'http://snomed.info/sct', 'SNOMED CT');
INSERT INTO coding_systems VALUES (4, 'http://loinc.org', 'LOINC');

CREATE TABLE value_sets (
    vs_id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    version TEXT DEFAULT '20240307',
    status TEXT DEFAULT 'active'
);

INSERT INTO value_sets VALUES (1, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.104.12.1011', 'Essential Hypertension', '20240307', 'active');
INSERT INTO value_sets VALUES (2, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1001', 'Adult Outpatient Qualifying Encounters', '20240307', 'active');
INSERT INTO value_sets VALUES (3, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.666.5.307', 'Encounter Inpatient', '20240307', 'active');
INSERT INTO value_sets VALUES (4, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1010', 'Emergency Department Evaluation and Management Visit', '20240307', 'active');
INSERT INTO value_sets VALUES (5, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.378', 'Pregnancy Dx', '20240307', 'active');
INSERT INTO value_sets VALUES (6, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.353', 'End Stage Renal Disease', '20240307', 'active');
INSERT INTO value_sets VALUES (7, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.1002', 'Chronic Kidney Disease, Stage 5', '20240307', 'active');
INSERT INTO value_sets VALUES (8, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1029', 'Kidney Transplant Recipient', '20240307', 'active');
INSERT INTO value_sets VALUES (9, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1012', 'Kidney Transplant', '20240307', 'active');
INSERT INTO value_sets VALUES (10, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1013', 'Dialysis Services', '20240307', 'active');
INSERT INTO value_sets VALUES (11, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1014', 'ESRD Monthly Outpatient Services', '20240307', 'active');
INSERT INTO value_sets VALUES (12, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.3157.1004.20', 'Hospice Encounter', '20240307', 'active');
INSERT INTO value_sets VALUES (13, 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.1167', 'Palliative Care Intervention', '20240307', 'active');

CREATE TABLE vs_expansion (
    vs_id INTEGER NOT NULL REFERENCES value_sets(vs_id),
    system_id INTEGER NOT NULL REFERENCES coding_systems(system_id),
    code TEXT NOT NULL,
    display TEXT,
    PRIMARY KEY (vs_id, system_id, code)
);

-- Essential Hypertension
INSERT INTO vs_expansion VALUES (1, 1, 'I10', 'Essential (primary) hypertension');
INSERT INTO vs_expansion VALUES (1, 1, 'I11.9', 'Hypertensive heart disease without heart failure');
INSERT INTO vs_expansion VALUES (1, 1, 'I13.10', 'Hypertensive heart and chronic kidney disease');

-- Adult Outpatient Qualifying Encounters
INSERT INTO vs_expansion VALUES (2, 2, '99213', 'Office visit, established patient, low complexity');
INSERT INTO vs_expansion VALUES (2, 2, '99214', 'Office visit, established patient, moderate complexity');
INSERT INTO vs_expansion VALUES (2, 2, '99215', 'Office visit, established patient, high complexity');
INSERT INTO vs_expansion VALUES (2, 2, '99395', 'Periodic preventive medicine, 18-39 years');
INSERT INTO vs_expansion VALUES (2, 2, '99396', 'Periodic preventive medicine, 40-64 years');
INSERT INTO vs_expansion VALUES (2, 2, '99397', 'Periodic preventive medicine, 65+ years');
INSERT INTO vs_expansion VALUES (2, 2, '99341', 'Home visit, new patient');
INSERT INTO vs_expansion VALUES (2, 2, '99342', 'Home visit, new patient, moderate complexity');
INSERT INTO vs_expansion VALUES (2, 2, '99421', 'Online digital evaluation, 5-10 minutes');
INSERT INTO vs_expansion VALUES (2, 2, '98966', 'Telephone assessment, 5-10 minutes');
INSERT INTO vs_expansion VALUES (2, 2, '99385', 'Initial preventive medicine, 18-39 years');
INSERT INTO vs_expansion VALUES (2, 2, '99386', 'Initial preventive medicine, 40-64 years');
INSERT INTO vs_expansion VALUES (2, 2, '99387', 'Initial preventive medicine, 65+ years');

-- Encounter Inpatient
INSERT INTO vs_expansion VALUES (3, 2, '99221', 'Initial hospital care, low complexity');
INSERT INTO vs_expansion VALUES (3, 2, '99222', 'Initial hospital care, moderate complexity');
INSERT INTO vs_expansion VALUES (3, 2, '99223', 'Initial hospital care, high complexity');
INSERT INTO vs_expansion VALUES (3, 3, '32485007', 'Hospital admission');

-- Emergency Department Evaluation and Management Visit
INSERT INTO vs_expansion VALUES (4, 2, '99281', 'ED visit, self-limited problem');
INSERT INTO vs_expansion VALUES (4, 2, '99282', 'ED visit, low complexity');
INSERT INTO vs_expansion VALUES (4, 2, '99283', 'ED visit, moderate complexity');
INSERT INTO vs_expansion VALUES (4, 2, '99284', 'ED visit, high complexity');
INSERT INTO vs_expansion VALUES (4, 2, '99285', 'ED visit, high complexity with threat');

-- Pregnancy Dx
INSERT INTO vs_expansion VALUES (5, 1, 'O09.90', 'Supervision of high risk pregnancy, unspecified');
INSERT INTO vs_expansion VALUES (5, 1, 'O80', 'Encounter for full-term uncomplicated delivery');
INSERT INTO vs_expansion VALUES (5, 1, 'Z33.1', 'Pregnant state, incidental');
INSERT INTO vs_expansion VALUES (5, 1, 'O26.90', 'Pregnancy related condition, unspecified');

-- End Stage Renal Disease
INSERT INTO vs_expansion VALUES (6, 1, 'N18.6', 'End stage renal disease');

-- Chronic Kidney Disease, Stage 5
INSERT INTO vs_expansion VALUES (7, 1, 'N18.5', 'Chronic kidney disease, stage 5');

-- Kidney Transplant Recipient
INSERT INTO vs_expansion VALUES (8, 1, 'Z94.0', 'Kidney transplant status');

-- Kidney Transplant
INSERT INTO vs_expansion VALUES (9, 2, '50360', 'Renal allotransplantation, implantation');
INSERT INTO vs_expansion VALUES (9, 2, '50365', 'Renal allotransplantation, from living donor');

-- Dialysis Services
INSERT INTO vs_expansion VALUES (10, 2, '90935', 'Hemodialysis procedure with single evaluation');
INSERT INTO vs_expansion VALUES (10, 2, '90937', 'Hemodialysis procedure requiring repeated evaluation');

-- ESRD Monthly Outpatient Services
INSERT INTO vs_expansion VALUES (11, 2, '90960', 'ESRD related services, per full month, age 20+');
INSERT INTO vs_expansion VALUES (11, 2, '90961', 'ESRD related services, per full month, age 12-19');

-- Hospice Encounter
INSERT INTO vs_expansion VALUES (12, 3, '385763009', 'Hospice care');
INSERT INTO vs_expansion VALUES (12, 3, '385765002', 'Hospice care management');

-- Palliative Care Intervention
INSERT INTO vs_expansion VALUES (13, 3, '443761007', 'Anticipatory palliative care');
INSERT INTO vs_expansion VALUES (13, 1, 'Z51.5', 'Encounter for palliative care');
