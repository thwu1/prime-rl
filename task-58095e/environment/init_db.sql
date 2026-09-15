-- Seismic Hazard Source Model Database
-- Schema for PSHA computation

CREATE TABLE sources (
    source_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('fault', 'point')),
    description TEXT
);

CREATE TABLE fault_traces (
    source_id INTEGER REFERENCES sources(source_id),
    point_order INTEGER NOT NULL,
    longitude REAL NOT NULL,
    latitude REAL NOT NULL,
    PRIMARY KEY (source_id, point_order)
);

CREATE TABLE fault_properties (
    source_id INTEGER PRIMARY KEY REFERENCES sources(source_id),
    dip_degrees REAL NOT NULL,
    rake_degrees REAL NOT NULL,
    upper_depth_km REAL NOT NULL,
    lower_depth_km REAL NOT NULL
);

CREATE TABLE point_locations (
    source_id INTEGER PRIMARY KEY REFERENCES sources(source_id),
    longitude REAL NOT NULL,
    latitude REAL NOT NULL,
    depth_km REAL NOT NULL
);

CREATE TABLE mfd_parameters (
    source_id INTEGER PRIMARY KEY REFERENCES sources(source_id),
    mfd_type TEXT NOT NULL CHECK(mfd_type IN ('GR', 'SINGLE')),
    a_value REAL,
    b_value REAL,
    m_min REAL,
    m_max REAL,
    delta_m REAL,
    magnitude REAL,
    rate REAL
);

CREATE TABLE gmm_tree (
    gmm_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE gmm_coefficients (
    gmm_id INTEGER REFERENCES gmm_tree(gmm_id),
    coefficient_name TEXT NOT NULL,
    coefficient_value REAL NOT NULL,
    PRIMARY KEY (gmm_id, coefficient_name)
);

CREATE TABLE model_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Source data
INSERT INTO sources VALUES (1, 'Fault-A', 'fault', 'Vertical strike-slip fault');
INSERT INTO sources VALUES (2, 'Fault-B', 'fault', 'Dipping reverse fault');
INSERT INTO sources VALUES (101, 'Grid-1', 'point', 'Background seismicity zone 1');
INSERT INTO sources VALUES (102, 'Grid-2', 'point', 'Background seismicity zone 2');

-- Fault traces
INSERT INTO fault_traces VALUES (1, 0, -122.5, 38.2);
INSERT INTO fault_traces VALUES (1, 1, -121.8, 37.8);
INSERT INTO fault_traces VALUES (2, 0, -122.2, 38.3);
INSERT INTO fault_traces VALUES (2, 1, -121.8, 37.9);

-- Fault properties
INSERT INTO fault_properties VALUES (1, 90.0, 0.0, 0.0, 12.0);
INSERT INTO fault_properties VALUES (2, 60.0, 90.0, 0.0, 15.0);

-- Point source locations
INSERT INTO point_locations VALUES (101, -122.2, 37.9, 10.0);
INSERT INTO point_locations VALUES (102, -121.8, 38.1, 8.0);

-- Magnitude-frequency distributions
INSERT INTO mfd_parameters VALUES (1, 'GR', 3.5, 0.9, 5.0, 7.5, 0.1, NULL, NULL);
INSERT INTO mfd_parameters VALUES (2, 'SINGLE', NULL, NULL, NULL, NULL, NULL, 7.0, 0.005);
INSERT INTO mfd_parameters VALUES (101, 'GR', 1.5, 1.0, 5.0, 6.5, 0.1, NULL, NULL);
INSERT INTO mfd_parameters VALUES (102, 'GR', 1.3, 1.0, 5.0, 6.5, 0.1, NULL, NULL);

-- GMM logic tree
INSERT INTO gmm_tree VALUES (1, 'GMM-A', 0.6);
INSERT INTO gmm_tree VALUES (2, 'GMM-B', 0.4);

-- GMM coefficients (entity-attribute-value pattern)
INSERT INTO gmm_coefficients VALUES (1, 'c0', 0.6);
INSERT INTO gmm_coefficients VALUES (1, 'c1', 1.0);
INSERT INTO gmm_coefficients VALUES (1, 'c2', -0.10);
INSERT INTO gmm_coefficients VALUES (1, 'c3', -0.8);
INSERT INTO gmm_coefficients VALUES (1, 'h_sq', 25.0);
INSERT INTO gmm_coefficients VALUES (1, 'c_site', 0.4);
INSERT INTO gmm_coefficients VALUES (1, 'v_ref', 760.0);
INSERT INTO gmm_coefficients VALUES (1, 'sigma', 0.65);
INSERT INTO gmm_coefficients VALUES (2, 'c0', 0.3);
INSERT INTO gmm_coefficients VALUES (2, 'c1', 0.9);
INSERT INTO gmm_coefficients VALUES (2, 'c2', -0.08);
INSERT INTO gmm_coefficients VALUES (2, 'c3', -0.75);
INSERT INTO gmm_coefficients VALUES (2, 'h_sq', 36.0);
INSERT INTO gmm_coefficients VALUES (2, 'c_site', 0.35);
INSERT INTO gmm_coefficients VALUES (2, 'v_ref', 760.0);
INSERT INTO gmm_coefficients VALUES (2, 'sigma', 0.60);

-- Model metadata
INSERT INTO model_metadata VALUES ('name', 'Bay Area Simplified Hazard Model');
INSERT INTO model_metadata VALUES ('max_distance_km', '200.0');
INSERT INTO model_metadata VALUES ('gmm_formula', 'mu = c0 + c1*(M-6) + c2*(M-6)^2 + c3*ln(sqrt(R_JB^2 + h_sq)) + c_site*ln(Vs30/v_ref)');
INSERT INTO model_metadata VALUES ('gmm_units', 'mu and sigma are natural log of PGA in g');
INSERT INTO model_metadata VALUES ('distance_metric', 'R_JB (Joyner-Boore)');
INSERT INTO model_metadata VALUES ('coordinate_convention', 'WGS84 degrees; local Cartesian uses 111.195 km/deg with cos(latitude) longitude correction');
