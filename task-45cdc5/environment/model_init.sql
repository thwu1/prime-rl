-- Ground motion model database
-- Contains GMM logic tree, regression coefficients, and PSHA metadata

CREATE TABLE gmm_tree (
    id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE gmm_coefficients (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES gmm_tree(id),
    param TEXT NOT NULL,
    value REAL NOT NULL
);

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- GMM tree
INSERT INTO gmm_tree VALUES (1, 'BA08s', 0.6);
INSERT INTO gmm_tree VALUES (2, 'CY08s', 0.4);

-- GMM coefficients: BA08s
INSERT INTO gmm_coefficients VALUES (1, 1, 'c1', -0.500);
INSERT INTO gmm_coefficients VALUES (2, 1, 'c2', 0.800);
INSERT INTO gmm_coefficients VALUES (3, 1, 'c3', -0.035);
INSERT INTO gmm_coefficients VALUES (4, 1, 'c4', -0.850);
INSERT INTO gmm_coefficients VALUES (5, 1, 'c5', 0.120);
INSERT INTO gmm_coefficients VALUES (6, 1, 'c6', 6.0);
INSERT INTO gmm_coefficients VALUES (7, 1, 'c7', -0.480);
INSERT INTO gmm_coefficients VALUES (8, 1, 'c8', 0.520);
INSERT INTO gmm_coefficients VALUES (9, 1, 'c9', 0.015);

-- GMM coefficients: CY08s
INSERT INTO gmm_coefficients VALUES (10, 2, 'c1', -0.700);
INSERT INTO gmm_coefficients VALUES (11, 2, 'c2', 0.750);
INSERT INTO gmm_coefficients VALUES (12, 2, 'c3', -0.045);
INSERT INTO gmm_coefficients VALUES (13, 2, 'c4', -0.900);
INSERT INTO gmm_coefficients VALUES (14, 2, 'c5', 0.100);
INSERT INTO gmm_coefficients VALUES (15, 2, 'c6', 5.0);
INSERT INTO gmm_coefficients VALUES (16, 2, 'c7', -0.420);
INSERT INTO gmm_coefficients VALUES (17, 2, 'c8', 0.550);
INSERT INTO gmm_coefficients VALUES (18, 2, 'c9', 0.010);

-- Metadata: mathematical specifications for PSHA computation
INSERT INTO metadata VALUES ('gmm_functional_form', 'ln(Y) = c1 + c2*(M - Mref) + c3*(M - Mref)^2 + (c4 + c5*(M - Mref)) * ln(sqrt(R^2 + c6^2)) + c7 * ln(Vs30 / Vref)');
INSERT INTO metadata VALUES ('gmm_sigma_model', 'sigma_total = c8 + c9 * M');
INSERT INTO metadata VALUES ('gmm_Mref', '6.0');
INSERT INTO metadata VALUES ('gmm_Vref', '760.0');
INSERT INTO metadata VALUES ('distance_metric_fault', 'rJB: shortest horizontal distance from site to vertical projection of fault rupture surface onto Earths surface');
INSERT INTO metadata VALUES ('distance_metric_grid', 'rHyp: hypocentral distance = sqrt(r_horizontal^2 + depth^2)');
INSERT INTO metadata VALUES ('exceedance_formula', 'P(Y > y | M, R) = [Phi(n) - Phi(eps)] / Phi(n) if eps < n, else 0; where eps = (ln(y) - mu) / sigma; Phi(x) = 0.5 * (1 + erf(x / sqrt(2))); n = truncation_level');
INSERT INTO metadata VALUES ('flat_earth_dx', 'dx_km = (lon2 - lon1) * cos(lat_site * pi/180) * 111.195');
INSERT INTO metadata VALUES ('flat_earth_dy', 'dy_km = (lat2 - lat1) * 111.195');
INSERT INTO metadata VALUES ('rjb_vertical_fault', 'For dip=90 deg the surface projection is the fault trace itself (line segments). rJB = shortest distance from site to any trace segment.');
INSERT INTO metadata VALUES ('rjb_dipping_fault', 'For dip<90 deg the surface projection is a polygon. Trace endpoints are extended by W*cos(dip) in the dip_direction to form a quadrilateral strip. rJB=0 if site lies inside the polygon.');
INSERT INTO metadata VALUES ('gr_incremental_rate', 'rate(M_i) = 10^(a - b*(M_i - dMag/2)) - 10^(a - b*(M_i + dMag/2)); bins centered at mMin, mMin+dMag, mMin+2*dMag, ..., mMax');
INSERT INTO metadata VALUES ('hazard_integral', 'lambda(Y>y) = SUM_sources[ SUM_mfd_branches[ w_branch * SUM_mag_bins[ rate(M_i) * SUM_gmm[ w_gmm * P(Y>y|M_i,R) ] ] ] ]');
INSERT INTO metadata VALUES ('mfd_logic_tree_note', 'Multiple MFD entries for one fault source are epistemic logic tree branches. Branch weights form a discrete probability distribution over alternative magnitude-frequency models.');
INSERT INTO metadata VALUES ('data_provenance', 'Merged from overlapping USGS regional catalogs and manual fault digitization records. Quality issues may exist from catalog overlaps and data entry errors.');
