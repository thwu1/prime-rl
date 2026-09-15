-- Pharmacology reference database for medication safety audit

CREATE TABLE renal_adjustments (
    drug_name TEXT NOT NULL,
    egfr_min REAL NOT NULL,
    egfr_max REAL NOT NULL,
    action TEXT NOT NULL,
    adjusted_dose TEXT
);

-- Metformin: NO_CHANGE >=60, REDUCE 30-59, STOP <30
INSERT INTO renal_adjustments VALUES ('metformin', 60, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('metformin', 30, 60, 'REDUCE', 'Max 1000 mg/day total');
INSERT INTO renal_adjustments VALUES ('metformin', 0, 30, 'STOP', NULL);

-- Digoxin: NO_CHANGE >=30, REDUCE <30
INSERT INTO renal_adjustments VALUES ('digoxin', 30, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('digoxin', 0, 30, 'REDUCE', 'Reduce dose by 50%');

-- Gabapentin: NO_CHANGE >=60, REDUCE 600 30-59, REDUCE 300 <30
INSERT INTO renal_adjustments VALUES ('gabapentin', 60, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('gabapentin', 30, 60, 'REDUCE', 'Max 600 mg/day total');
INSERT INTO renal_adjustments VALUES ('gabapentin', 0, 30, 'REDUCE', 'Max 300 mg/day total');

-- Dabigatran: NO_CHANGE >=30, REDUCE 15-29, STOP <15
INSERT INTO renal_adjustments VALUES ('dabigatran', 30, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('dabigatran', 15, 30, 'REDUCE', '75 mg BID');
INSERT INTO renal_adjustments VALUES ('dabigatran', 0, 15, 'STOP', NULL);

-- Allopurinol: NO_CHANGE >=60, REDUCE 200 30-59, REDUCE 100 15-29, STOP <15
INSERT INTO renal_adjustments VALUES ('allopurinol', 60, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('allopurinol', 30, 60, 'REDUCE', 'Max 200 mg/day total');
INSERT INTO renal_adjustments VALUES ('allopurinol', 15, 30, 'REDUCE', 'Max 100 mg/day total');
INSERT INTO renal_adjustments VALUES ('allopurinol', 0, 15, 'STOP', NULL);

-- Rivaroxaban: NO_CHANGE >=60, REDUCE 15-59, STOP <15
INSERT INTO renal_adjustments VALUES ('rivaroxaban', 60, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('rivaroxaban', 15, 60, 'REDUCE', '15 mg daily');
INSERT INTO renal_adjustments VALUES ('rivaroxaban', 0, 15, 'STOP', NULL);

-- Apixaban: NO_CHANGE >=30, REDUCE 15-29, STOP <15
INSERT INTO renal_adjustments VALUES ('apixaban', 30, 10000, 'NO_CHANGE', NULL);
INSERT INTO renal_adjustments VALUES ('apixaban', 15, 30, 'REDUCE', '2.5 mg BID');
INSERT INTO renal_adjustments VALUES ('apixaban', 0, 15, 'STOP', NULL);

CREATE TABLE drug_interactions (
    drug_a TEXT NOT NULL,
    drug_b TEXT NOT NULL,
    severity TEXT NOT NULL,
    clinical_effect TEXT NOT NULL,
    recommendation TEXT NOT NULL
);

INSERT INTO drug_interactions VALUES ('digoxin', 'apixaban', 'MODERATE', 'Increased bleeding risk with renal impairment; both drugs have reduced clearance', 'Monitor for bleeding; reassess need for dual therapy');
INSERT INTO drug_interactions VALUES ('dabigatran', 'allopurinol', 'MODERATE', 'Allopurinol may decrease renal clearance of dabigatran', 'Monitor renal function and signs of bleeding');
INSERT INTO drug_interactions VALUES ('metformin', 'lisinopril', 'LOW', 'ACE inhibitors may potentiate hypoglycemic effects', 'Monitor blood glucose');
INSERT INTO drug_interactions VALUES ('rivaroxaban', 'amlodipine', 'LOW', 'Amlodipine is a weak P-glycoprotein inhibitor; minor increase in rivaroxaban exposure', 'No dose adjustment typically required');
INSERT INTO drug_interactions VALUES ('gabapentin', 'dabigatran', 'LOW', 'Both renally eliminated; combined renal impairment may increase levels of both', 'Monitor renal function');

CREATE TABLE therapeutic_categories (
    drug_name TEXT NOT NULL,
    category TEXT NOT NULL
);

INSERT INTO therapeutic_categories VALUES ('metformin', 'antidiabetic');
INSERT INTO therapeutic_categories VALUES ('digoxin', 'cardiac_glycoside');
INSERT INTO therapeutic_categories VALUES ('gabapentin', 'anticonvulsant');
INSERT INTO therapeutic_categories VALUES ('dabigatran', 'anticoagulant');
INSERT INTO therapeutic_categories VALUES ('allopurinol', 'antigout');
INSERT INTO therapeutic_categories VALUES ('rivaroxaban', 'anticoagulant');
INSERT INTO therapeutic_categories VALUES ('apixaban', 'anticoagulant');
INSERT INTO therapeutic_categories VALUES ('lisinopril', 'ace_inhibitor');
INSERT INTO therapeutic_categories VALUES ('atorvastatin', 'statin');
INSERT INTO therapeutic_categories VALUES ('amlodipine', 'calcium_channel_blocker');
