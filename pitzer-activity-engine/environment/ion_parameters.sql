-- Ion-interaction parameter database for binary aqueous electrolytes at 25 C (298.15 K)

CREATE TABLE IF NOT EXISTS constants (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    unit TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS salt_parameters (
    salt_name TEXT PRIMARY KEY,
    cation TEXT NOT NULL,
    anion TEXT NOT NULL,
    z_cation INTEGER NOT NULL,
    z_anion INTEGER NOT NULL,
    nu_cation INTEGER NOT NULL,
    nu_anion INTEGER NOT NULL,
    Beta0 REAL NOT NULL,
    Beta1 REAL NOT NULL,
    Beta2 REAL NOT NULL DEFAULT 0.0,
    Cphi REAL NOT NULL DEFAULT 0.0,
    alpha1 REAL NOT NULL DEFAULT 2.0,
    alpha2 REAL NOT NULL DEFAULT 0.0
);

INSERT OR REPLACE INTO constants (key, value, unit, notes) VALUES
('A_phi', 0.3915, '(kg/mol)^0.5', 'Osmotic coefficient limiting slope at 25C'),
('b', 1.2, '(kg/mol)^0.5', 'Short-range interaction distance parameter'),
('R', 8.314, 'J/(mol*K)', 'Ideal gas constant'),
('M_w', 0.018015, 'kg/mol', 'Molar mass of water'),
('T_ref', 298.15, 'K', 'Reference temperature'),
('V_w', 1.8015e-05, 'm^3/mol', 'Molar volume of pure water at 25C and 1 atm');

INSERT OR REPLACE INTO salt_parameters (salt_name, cation, anion, z_cation, z_anion, nu_cation, nu_anion, Beta0, Beta1, Beta2, Cphi, alpha1, alpha2) VALUES
('NaCl',  'Na+',  'Cl-',   1, -1, 1, 1, 0.0765,  0.2664, 0.0, 0.00127,  2.0, 0.0),
('KCl',   'K+',   'Cl-',   1, -1, 1, 1, 0.04835, 0.2122, 0.0, -0.00084, 2.0, 0.0),
('KBr',   'K+',   'Br-',   1, -1, 1, 1, 0.0569,  0.2212, 0.0, -0.00180, 2.0, 0.0),
('LiCl',  'Li+',  'Cl-',   1, -1, 1, 1, 0.1494,  0.3074, 0.0, 0.00359,  2.0, 0.0),
('HCl',   'H+',   'Cl-',   1, -1, 1, 1, 0.1775,  0.2945, 0.0, 0.00080,  2.0, 0.0),
('RbCl',  'Rb+',  'Cl-',   1, -1, 1, 1, 0.0441,  0.0396, 0.0, -0.00050, 2.0, 0.0),
('BaCl2', 'Ba+2', 'Cl-',   2, -1, 1, 2, 0.2628,  1.4963, 0.0, -0.01938, 2.0, 0.0),
('K2SO4', 'K+',   'SO4-2', 1, -2, 2, 1, 0.04995, 0.7793, 0.0, 0.0,      2.0, 0.0);
