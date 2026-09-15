-- Clinical Parameters Database Schema and Seed Data
-- Contains formula coefficients and clinical thresholds for blood gas assessment

CREATE TABLE formula_coefficients (
    formula TEXT NOT NULL,
    param TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    PRIMARY KEY (formula, param)
);

CREATE TABLE clinical_thresholds (
    metric TEXT NOT NULL,
    boundary TEXT NOT NULL,
    value REAL NOT NULL,
    classification TEXT,
    PRIMARY KEY (metric, boundary)
);

-- Anion gap correction parameters
INSERT INTO formula_coefficients VALUES ('ag_correction', 'reference_albumin', 44.0, 'g/L');
INSERT INTO formula_coefficients VALUES ('ag_correction', 'factor', 0.25, 'mmol_per_gL');

-- Electrolyte correction parameters
INSERT INTO formula_coefficients VALUES ('potassium_correction', 'factor', 0.4, 'mmol_per_unit_pH');
INSERT INTO formula_coefficients VALUES ('potassium_correction', 'reference_pH', 7.4, NULL);
INSERT INTO formula_coefficients VALUES ('potassium_correction', 'pH_step', 0.1, NULL);
INSERT INTO formula_coefficients VALUES ('sodium_correction', 'factor', 1.5, NULL);
INSERT INTO formula_coefficients VALUES ('sodium_correction', 'reference_glucose', 5.5, 'mmol/L');

-- Winters' formula (metabolic acidosis compensation)
INSERT INTO formula_coefficients VALUES ('winters_formula', 'hco3_multiplier', 1.5, NULL);
INSERT INTO formula_coefficients VALUES ('winters_formula', 'intercept', 8.0, 'mmHg');
INSERT INTO formula_coefficients VALUES ('met_acid_compensation', 'tolerance', 5.0, 'mmHg');

-- Metabolic alkalosis compensation
INSERT INTO formula_coefficients VALUES ('met_alk_compensation', 'coefficient', 0.6, NULL);
INSERT INTO formula_coefficients VALUES ('met_alk_compensation', 'intercept', 20.0, 'mmHg');
INSERT INTO formula_coefficients VALUES ('met_alk_compensation', 'tolerance', 5.0, 'mmHg');

-- Respiratory compensation (1-2-3-4-5 rule)
INSERT INTO formula_coefficients VALUES ('resp_compensation_acute', 'acidosis_factor', 1.0, NULL);
INSERT INTO formula_coefficients VALUES ('resp_compensation_acute', 'alkalosis_factor', 2.0, NULL);
INSERT INTO formula_coefficients VALUES ('resp_compensation_chronic', 'acidosis_factor', 4.0, NULL);
INSERT INTO formula_coefficients VALUES ('resp_compensation_chronic', 'alkalosis_factor', 5.0, NULL);
INSERT INTO formula_coefficients VALUES ('resp_compensation', 'pco2_step', 10.0, 'mmHg');
INSERT INTO formula_coefficients VALUES ('resp_compensation', 'reference_hco3', 24.0, 'mmol/L');
INSERT INTO formula_coefficients VALUES ('resp_compensation', 'reference_pco2', 40.0, 'mmHg');
INSERT INTO formula_coefficients VALUES ('resp_compensation', 'tolerance', 3.0, 'mmol/L');

-- Osmolarity calculation
INSERT INTO formula_coefficients VALUES ('osmolarity', 'na_factor', 2.0, NULL);
INSERT INTO formula_coefficients VALUES ('osmolarity', 'ethanol_divisor', 4.6, NULL);
INSERT INTO formula_coefficients VALUES ('osmolarity', 'ethanol_factor', 1.25, NULL);

-- Stewart approach - SID
INSERT INTO formula_coefficients VALUES ('sid_apparent', 'divalent_factor', 2.0, NULL);

-- Figge-Fencl albumin charge approximation
INSERT INTO formula_coefficients VALUES ('figge_fencl', 'ph_coefficient', 0.123, NULL);
INSERT INTO formula_coefficients VALUES ('figge_fencl', 'intercept', -0.631, NULL);

-- Clinical thresholds
INSERT INTO clinical_thresholds VALUES ('anion_gap', 'upper', 12.0, 'high');
INSERT INTO clinical_thresholds VALUES ('anion_gap', 'lower', 4.0, 'low');
INSERT INTO clinical_thresholds VALUES ('delta_ratio', 'nagma_upper', 0.4, 'pure_nagma');
INSERT INTO clinical_thresholds VALUES ('delta_ratio', 'mixed_upper', 0.8, 'mixed_hagma_nagma');
INSERT INTO clinical_thresholds VALUES ('delta_ratio', 'hagma_upper', 2.0, 'pure_hagma');
INSERT INTO clinical_thresholds VALUES ('delta_ratio', 'reference_ag', 12.0, NULL);
INSERT INTO clinical_thresholds VALUES ('delta_ratio', 'reference_hco3', 24.0, NULL);
INSERT INTO clinical_thresholds VALUES ('pf_ratio', 'severe', 100.0, 'severe');
INSERT INTO clinical_thresholds VALUES ('pf_ratio', 'moderate', 200.0, 'moderate');
INSERT INTO clinical_thresholds VALUES ('pf_ratio', 'mild', 300.0, 'mild');
INSERT INTO clinical_thresholds VALUES ('o2er', 'upper', 0.30, 'high');
INSERT INTO clinical_thresholds VALUES ('o2er', 'lower', 0.20, 'low');
INSERT INTO clinical_thresholds VALUES ('osmolar_gap', 'upper', 10.0, 'elevated');
INSERT INTO clinical_thresholds VALUES ('pco2_gap', 'upper', 5.0, 'elevated');
