-- PhysioNet Challenge 2026 Clinical Database
-- Multi-source schema with EHR, claims, linkage, and site configuration

CREATE TABLE psg_sessions (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    site_code TEXT NOT NULL,
    study_date TEXT NOT NULL,
    last_followup_date TEXT NOT NULL,
    age_at_study REAL,
    sex TEXT,
    bmi REAL
);

CREATE TABLE ehr_diagnoses (
    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    icd_code TEXT NOT NULL,
    diagnosis_date TEXT NOT NULL,
    encounter_type TEXT DEFAULT 'outpatient',
    provider_id TEXT
);

CREATE TABLE claims_diagnoses (
    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id TEXT NOT NULL,
    diagnosis_code TEXT NOT NULL,
    service_date TEXT NOT NULL,
    claim_type TEXT DEFAULT 'professional',
    rendering_provider TEXT
);

CREATE TABLE patient_linkage (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    site_code TEXT NOT NULL,
    linkage_date TEXT NOT NULL
);

CREATE TABLE site_parameters (
    param_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    parameter_value TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    notes TEXT
);

CREATE INDEX idx_ehr_patient ON ehr_diagnoses(patient_id);
CREATE INDEX idx_claims_member ON claims_diagnoses(member_id);
CREATE INDEX idx_linkage_patient ON patient_linkage(patient_id);
CREATE INDEX idx_linkage_member ON patient_linkage(member_id);
CREATE INDEX idx_session_patient ON psg_sessions(patient_id);
CREATE INDEX idx_site_params ON site_parameters(site_code, parameter_name);

-- PSG sessions (30 patients)
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P001', 'S0001', '2010-03-15', '2018-05-01', 68.2, 'M', 27.3);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P002', 'S0001', '2011-01-10', '2019-06-01', 72.5, 'F', 24.8);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P003', 'I0006', '2010-07-15', '2019-07-01', 66.8, 'F', 26.4);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P004', 'S0001', '2010-09-20', '2019-11-01', 78.1, 'F', 22.1);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P005', 'I0002', '2011-03-01', '2020-05-01', 70.3, 'M', 29.5);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P006', 'S0001', '2010-01-01', '2019-01-01', 74.9, 'M', 28.7);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P007', 'S0001', '2012-06-01', '2020-01-01', 65.0, 'M', 31.2);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P008', 'S0001', '2009-06-01', '2018-01-01', 71.0, 'F', 27.9);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P009', 'I0004', '2010-06-01', '2019-06-01', 60.3, 'M', 25.1);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P010', 'S0001', '2011-01-01', '2019-06-01', 58.9, 'F', 24.7);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P011', 'S0001', '2010-01-01', '2019-06-01', 55.2, 'F', 23.5);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P012', 'S0001', '2011-03-15', '2020-01-01', 62.1, 'M', 25.8);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P013', 'S0001', '2010-06-01', '2018-08-01', 59.7, 'F', 30.1);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P014', 'S0001', '2012-01-01', '2021-06-01', 48.3, 'M', 22.9);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P015', 'I0002', '2012-06-01', '2019-01-01', 71.4, 'M', 24.3);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P016', 'S0001', '2011-07-01', '2019-12-01', 53.6, 'F', 27.6);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P017', 'I0006', '2011-01-01', '2019-06-01', 67.9, 'F', 29.2);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P018', 'I0004', '2013-01-01', '2021-01-01', 44.8, 'M', 26.1);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P019', 'S0001', '2010-02-01', '2018-06-01', 63.5, 'M', 28.3);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P020', 'I0002', '2011-01-01', '2017-06-01', 69.4, 'F', 25.9);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P021', 'S0001', '2010-05-01', '2019-01-01', 76.2, 'F', 23.8);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P022', 'S0001', '2013-01-01', '2021-01-01', 69.5, 'M', 31.5);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P023', 'S0001', '2015-01-01', '2020-06-01', 61.3, 'F', 25.2);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P024', 'S0001', '2010-01-01', '2020-01-01', 73.7, 'M', 28.4);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P025', 'S0001', '2011-01-01', '2019-06-01', 58.9, 'F', 24.7);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P026', 'I0002', '2014-06-01', '2019-06-01', 80.1, 'M', 22.5);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P027', 'S0001', '2010-03-01', '2019-01-01', 64.8, 'F', 26.7);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P028', 'S0001', '2010-01-01', '2019-06-01', 57.3, 'M', 29.1);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P029', 'S0001', '2012-06-01', '2018-06-01', 66.1, 'F', 27.4);
INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES ('P030', 'I0004', '2014-01-01', '2019-06-01', 72.8, 'M', 23.9);

-- EHR diagnoses (dotted ICD codes from clinical encounters)
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P001', 'G31.84', '2013-06-20', 'outpatient', 'DR101');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P001', 'G30.9', '2014-01-10', 'outpatient', 'DR102');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P002', '331.83', '2015-02-15', 'outpatient', 'DR201');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P003', 'G30.0', '2016-07-15', 'outpatient', 'DR301');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P003', 'G30.1', '2016-08-01', 'outpatient', 'DR302');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P004', '290.0', '2014-01-05', 'inpatient', 'DR401');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P004', 'F03.90', '2014-03-10', 'outpatient', 'DR402');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P005', 'G31.84', '2014-06-15', 'outpatient', 'DR501');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P006', 'G31.84', '2011-06-01', 'outpatient', 'DR601');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P006', 'G30.0', '2014-01-01', 'inpatient', 'DR602');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P006', 'G30.9', '2015-06-01', 'outpatient', 'DR603');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P007', 'G30.0', '2016-07-15', 'outpatient', 'DR701');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P007', 'G30.1', '2016-08-01', 'outpatient', 'DR702');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P008', 'G31.84', '2012-09-01', 'outpatient', 'DR801');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P009', 'G31.83', '2014-02-01', 'outpatient', 'DR901');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P009', 'G31.84', '2014-11-15', 'outpatient', 'DR902');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P010', 'G31.84', '2014-06-01', 'outpatient', 'DR1001');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P011', 'I25.10', '2012-03-15', 'outpatient', 'DR1101');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P012', 'E78.5', '2013-07-22', 'outpatient', 'DR1201');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P013', 'J45.9', '2013-01-15', 'outpatient', 'DR1301');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P013', 'E11.9', '2014-06-01', 'outpatient', 'DR1302');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P013', 'I10', '2015-03-20', 'inpatient', 'DR1303');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P014', 'G47.33', '2014-05-01', 'outpatient', 'DR1401');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P018', 'M54.5', '2015-08-20', 'outpatient', 'DR1801');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P021', 'G31.84', '2014-06-01', 'outpatient', 'DR2101');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P022', 'G30.0', '2014-06-01', 'outpatient', 'DR2201');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P022', 'G30.1', '2014-09-01', 'outpatient', 'DR2202');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P023', 'R51', '2016-04-10', 'outpatient', 'DR2301');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P024', 'G31.84', '2018-06-01', 'outpatient', 'DR2401');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P024', 'G30.9', '2019-01-01', 'outpatient', 'DR2402');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P025', 'G30.0', '2015-03-01', 'outpatient', 'DR2501');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P025', 'G30.1', '2015-03-05', 'outpatient', 'DR2502');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P026', 'G47.00', '2015-09-01', 'outpatient', 'DR2601');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P027', 'G31.84', '2014-03-01', 'outpatient', 'DR2701');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P028', 'G30.0', '2016-01-01', 'outpatient', 'DR2801');
INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES ('P030', 'G47.30', '2016-01-15', 'outpatient', 'DR3001');

-- Claims diagnoses (undotted codes, different identifier system)
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M002', 'G3184', '2016-08-20', 'professional', 'NPI001');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M005', 'F0390', '2015-01-10', 'professional', 'NPI002');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M008', '33183', '2016-03-15', 'professional', 'NPI003');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M010', 'G3184', '2014-06-01', 'professional', 'NPI004');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M010', 'G309', '2015-09-01', 'professional', 'NPI005');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M016', 'J441', '2013-11-15', 'professional', 'NPI006');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M027', 'G3184', '2014-03-01', 'professional', 'NPI007');
INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES ('M028', 'G309', '2016-01-01', 'professional', 'NPI008');

-- Patient linkage (maps EHR patient_id to claims member_id)
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P002', 'M002', 'S0001', '2011-01-10');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P005', 'M005', 'I0002', '2011-03-01');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P008', 'M008', 'S0001', '2009-06-01');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P010', 'M010', 'S0001', '2011-01-01');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P016', 'M016', 'S0001', '2011-07-01');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P027', 'M027', 'S0001', '2010-03-01');
INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES ('P028', 'M028', 'S0001', '2010-01-01');

-- Site parameters (configurable evaluation thresholds per institution)
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('S0001', 'min_followup_years', '7.0', '2020-01-01', 'Standard minimum follow-up for CI-negative classification');
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('S0001', 'data_collection_start', '2005-01-01', '2020-01-01', NULL);
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0002', 'min_followup_years', '6.0', '2020-01-01', 'Reduced threshold due to shorter data availability at this site');
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0002', 'data_collection_start', '2008-01-01', '2020-01-01', NULL);
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0004', 'min_followup_years', '7.0', '2020-01-01', 'Standard minimum follow-up');
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0004', 'data_collection_start', '2006-01-01', '2020-01-01', NULL);
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0006', 'min_followup_years', '7.0', '2020-01-01', 'Standard minimum follow-up');
INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES ('I0006', 'data_collection_start', '2007-01-01', '2020-01-01', NULL);
