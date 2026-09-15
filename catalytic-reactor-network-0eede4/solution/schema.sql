-- Thermodynamic properties database for catalytic reactor simulation
-- Species adsorption equilibrium constants, heats of adsorption, and reference concentrations

CREATE TABLE IF NOT EXISTS species_properties (
    name TEXT PRIMARY KEY,
    adsorption_K REAL NOT NULL,
    heat_ads_kJ REAL NOT NULL,
    ref_conc REAL NOT NULL
);

-- Reference data compiled from literature sources
-- Columns: name, adsorption_K, heat_ads_kJ, ref_conc
INSERT INTO species_properties VALUES ('A',  2.0,  45.0, 0.50);
INSERT INTO species_properties VALUES ('B',  2.5,  38.0, 0.40);
INSERT INTO species_properties VALUES ('M',  0.5,  22.0, 0.10);
INSERT INTO species_properties VALUES ('N',  0.3,  18.0, 0.05);
INSERT INTO species_properties VALUES ('C',  0.8,  25.0, 0.20);
INSERT INTO species_properties VALUES ('D',  1.2,  30.0, 0.30);
