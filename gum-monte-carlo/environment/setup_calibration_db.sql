-- Calibration database for gauge block measurement uncertainty evaluation
-- Contains model metadata, input variable specifications, and raw measurement series

CREATE TABLE models (
  model_id TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  model_expression TEXT NOT NULL,
  nominal_length_nm REAL,
  coverage_probability REAL NOT NULL,
  ndig INTEGER NOT NULL
);

INSERT INTO models VALUES (
  'gauge_block',
  'End-gauge calibration by mechanical comparison. Nine input quantities with mixed evaluation types.',
  'delta_L = L_s + D + d1 + d2 - L_s * (delta_alpha * (theta_0 + Delta) + alpha_s * delta_theta) - L_nom',
  50000000.0,
  0.99,
  1
);

CREATE TABLE input_variables (
  id INTEGER PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES models(model_id),
  var_name TEXT NOT NULL,
  var_order INTEGER NOT NULL,
  eval_type TEXT NOT NULL CHECK(eval_type IN ('type_a', 'type_b')),
  description TEXT,
  unit TEXT
);

-- Type A inputs: statistics derived from repeated measurement observations
INSERT INTO input_variables VALUES (1, 'gauge_block', 'D', 2, 'type_a', 'Measured difference in length between artefact and standard', 'nm');
INSERT INTO input_variables VALUES (2, 'gauge_block', 'd1', 3, 'type_a', 'Random effect arising from comparator', 'nm');
INSERT INTO input_variables VALUES (3, 'gauge_block', 'd2', 4, 'type_a', 'Systematic effect arising from comparator', 'nm');

-- Type B inputs: distribution parameters assigned from prior knowledge
INSERT INTO input_variables VALUES (4, 'gauge_block', 'L_s', 1, 'type_b', 'Calibrated length of reference standard at 20 degC', 'nm');
INSERT INTO input_variables VALUES (5, 'gauge_block', 'alpha_s', 5, 'type_b', 'Thermal expansion coefficient of reference standard', 'per_degC');
INSERT INTO input_variables VALUES (6, 'gauge_block', 'theta_0', 6, 'type_b', 'Mean deviation of lab temperature from 20 degC', 'degC');
INSERT INTO input_variables VALUES (7, 'gauge_block', 'Delta', 7, 'type_b', 'Cyclic temperature variation amplitude', 'degC');
INSERT INTO input_variables VALUES (8, 'gauge_block', 'delta_alpha', 8, 'type_b', 'Difference in thermal expansion coefficients', 'per_degC');
INSERT INTO input_variables VALUES (9, 'gauge_block', 'delta_theta', 9, 'type_b', 'Temperature difference between artefact and standard', 'degC');

CREATE TABLE type_b_distributions (
  id INTEGER PRIMARY KEY,
  var_id INTEGER NOT NULL REFERENCES input_variables(id),
  distribution TEXT NOT NULL,
  param_mean REAL,
  param_std REAL,
  param_lower REAL,
  param_upper REAL,
  param_dof REAL,
  param_d REAL
);

-- L_s: Student's t (from calibration certificate)
INSERT INTO type_b_distributions VALUES (1, 4, 't', 50000623.0, 25.0, NULL, NULL, 18.0, NULL);
-- alpha_s: rectangular (from manufacturer spec)
INSERT INTO type_b_distributions VALUES (2, 5, 'rectangular', NULL, NULL, 9.5e-6, 13.5e-6, NULL, NULL);
-- theta_0: Gaussian
INSERT INTO type_b_distributions VALUES (3, 6, 'gaussian', -0.1, 0.2, NULL, NULL, NULL, NULL);
-- Delta: arcsine (U-shaped)
INSERT INTO type_b_distributions VALUES (4, 7, 'arcsine', NULL, NULL, -0.5, 0.5, NULL, NULL);
-- delta_alpha: curvilinear trapezoidal
INSERT INTO type_b_distributions VALUES (5, 8, 'curvilinear_trapezoidal', NULL, NULL, -1.0e-6, 1.0e-6, 50.0, 0.1e-6);
-- delta_theta: curvilinear trapezoidal
INSERT INTO type_b_distributions VALUES (6, 9, 'curvilinear_trapezoidal', NULL, NULL, -0.050, 0.050, 2.0, 0.025);

CREATE TABLE measurement_observations (
  id INTEGER PRIMARY KEY,
  quantity TEXT NOT NULL,
  trial_number INTEGER NOT NULL,
  value_nm REAL NOT NULL,
  recorded_at TEXT NOT NULL
);

INSERT INTO measurement_observations VALUES (1, 'D', 1, 215.0940254707, '2024-01-15 09:00:00');
INSERT INTO measurement_observations VALUES (2, 'D', 2, 225.5724157029, '2024-01-15 10:00:00');
INSERT INTO measurement_observations VALUES (3, 'D', 3, 242.3015228011, '2024-01-15 11:00:00');
INSERT INTO measurement_observations VALUES (4, 'D', 4, 181.5012783534, '2024-01-15 12:00:00');
INSERT INTO measurement_observations VALUES (5, 'D', 5, 197.8976938927, '2024-01-15 13:00:00');
INSERT INTO measurement_observations VALUES (6, 'D', 6, 247.6331253610, '2024-01-16 09:00:00');
INSERT INTO measurement_observations VALUES (7, 'D', 7, 192.5758025341, '2024-01-16 10:00:00');
INSERT INTO measurement_observations VALUES (8, 'D', 8, 208.8970125854, '2024-01-16 11:00:00');
INSERT INTO measurement_observations VALUES (9, 'D', 9, 262.3261001249, '2024-01-16 12:00:00');
INSERT INTO measurement_observations VALUES (10, 'D', 10, 261.9538661482, '2024-01-16 13:00:00');
INSERT INTO measurement_observations VALUES (11, 'D', 11, 191.0231897240, '2024-01-17 09:00:00');
INSERT INTO measurement_observations VALUES (12, 'D', 12, 209.1091813706, '2024-01-17 10:00:00');
INSERT INTO measurement_observations VALUES (13, 'D', 13, 174.2879183730, '2024-01-17 11:00:00');
INSERT INTO measurement_observations VALUES (14, 'D', 14, 205.2499561604, '2024-01-17 12:00:00');
INSERT INTO measurement_observations VALUES (15, 'D', 15, 244.3990344345, '2024-01-17 13:00:00');
INSERT INTO measurement_observations VALUES (16, 'D', 16, 215.6217019832, '2024-01-18 09:00:00');
INSERT INTO measurement_observations VALUES (17, 'D', 17, 276.5339311576, '2024-01-18 10:00:00');
INSERT INTO measurement_observations VALUES (18, 'D', 18, 214.3364835116, '2024-01-18 11:00:00');
INSERT INTO measurement_observations VALUES (19, 'D', 19, 191.3658374180, '2024-01-18 12:00:00');
INSERT INTO measurement_observations VALUES (20, 'D', 20, 220.9843170833, '2024-01-18 13:00:00');
INSERT INTO measurement_observations VALUES (21, 'D', 21, 214.9883595208, '2024-01-19 09:00:00');
INSERT INTO measurement_observations VALUES (22, 'D', 22, 187.5721757327, '2024-01-19 10:00:00');
INSERT INTO measurement_observations VALUES (23, 'D', 23, 215.3671425532, '2024-01-19 11:00:00');
INSERT INTO measurement_observations VALUES (24, 'D', 24, 231.5560220721, '2024-01-19 12:00:00');
INSERT INTO measurement_observations VALUES (25, 'D', 25, 146.8519059307, '2024-01-19 13:00:00');
INSERT INTO measurement_observations VALUES (101, 'd1', 1, 9.0684813400, '2024-01-20 10:00:00');
INSERT INTO measurement_observations VALUES (102, 'd1', 2, 3.8779860403, '2024-01-20 11:00:00');
INSERT INTO measurement_observations VALUES (103, 'd1', 3, -12.8270606307, '2024-01-20 12:00:00');
INSERT INTO measurement_observations VALUES (104, 'd1', 4, 10.4974736366, '2024-01-20 13:00:00');
INSERT INTO measurement_observations VALUES (105, 'd1', 5, -10.3895010428, '2024-01-20 14:00:00');
INSERT INTO measurement_observations VALUES (106, 'd1', 6, -0.2273793433, '2024-01-20 15:00:00');
INSERT INTO measurement_observations VALUES (201, 'd2', 1, -19.0424781088, '2024-01-21 09:00:00');
INSERT INTO measurement_observations VALUES (202, 'd2', 2, 8.4916782999, '2024-01-21 10:00:00');
INSERT INTO measurement_observations VALUES (203, 'd2', 3, 12.5928075939, '2024-01-21 11:00:00');
INSERT INTO measurement_observations VALUES (204, 'd2', 4, -29.4065726069, '2024-01-21 12:00:00');
INSERT INTO measurement_observations VALUES (205, 'd2', 5, 25.0340900010, '2024-01-21 13:00:00');
INSERT INTO measurement_observations VALUES (206, 'd2', 6, -22.7634661810, '2024-01-21 14:00:00');
INSERT INTO measurement_observations VALUES (207, 'd2', 7, -9.9626932967, '2024-01-21 15:00:00');
INSERT INTO measurement_observations VALUES (208, 'd2', 8, 7.2489690450, '2024-01-21 16:00:00');
INSERT INTO measurement_observations VALUES (209, 'd2', 9, 27.8076652536, '2024-01-21 17:00:00');
