-- CPIC supplementary gene data (normalized relational schema)

CREATE TABLE IF NOT EXISTS supplement_alleles (
    gene TEXT NOT NULL,
    allele_name TEXT NOT NULL,
    clinical_functional_status TEXT,
    activity_value REAL,
    PRIMARY KEY (gene, allele_name)
);

CREATE TABLE IF NOT EXISTS supplement_diplotypes (
    gene TEXT NOT NULL,
    diplotype TEXT NOT NULL,
    phenotype TEXT NOT NULL,
    PRIMARY KEY (gene, diplotype)
);

-- CYP3A5 allele function assignments
INSERT INTO supplement_alleles (gene, allele_name, clinical_functional_status, activity_value) VALUES
('CYP3A5', '*1', 'Normal function', NULL),
('CYP3A5', '*3', 'No function', NULL),
('CYP3A5', '*6', 'No function', NULL),
('CYP3A5', '*7', 'No function', NULL),
('CYP3A5', '*8', 'Unknown function', NULL),
('CYP3A5', '*9', 'Unknown function', NULL);

-- CYP3A5 diplotype-to-phenotype mappings
INSERT INTO supplement_diplotypes (gene, diplotype, phenotype) VALUES
('CYP3A5', '*1/*1', 'Normal Metabolizer'),
('CYP3A5', '*1/*3', 'Intermediate Metabolizer'),
('CYP3A5', '*1/*6', 'Intermediate Metabolizer'),
('CYP3A5', '*1/*7', 'Intermediate Metabolizer'),
('CYP3A5', '*3/*3', 'Poor Metabolizer'),
('CYP3A5', '*3/*6', 'Poor Metabolizer'),
('CYP3A5', '*3/*7', 'Poor Metabolizer'),
('CYP3A5', '*6/*6', 'Poor Metabolizer'),
('CYP3A5', '*6/*7', 'Poor Metabolizer'),
('CYP3A5', '*7/*7', 'Poor Metabolizer');

-- NUDT15 allele function assignments
INSERT INTO supplement_alleles (gene, allele_name, clinical_functional_status, activity_value) VALUES
('NUDT15', '*1', 'Normal function', NULL),
('NUDT15', '*2', 'No function', NULL),
('NUDT15', '*3', 'Decreased function', NULL),
('NUDT15', '*4', 'Decreased function', NULL),
('NUDT15', '*5', 'Decreased function', NULL),
('NUDT15', '*6', 'No function', NULL);

-- NUDT15 diplotype-to-phenotype mappings
INSERT INTO supplement_diplotypes (gene, diplotype, phenotype) VALUES
('NUDT15', '*1/*1', 'Normal Metabolizer'),
('NUDT15', '*1/*2', 'Intermediate Metabolizer'),
('NUDT15', '*1/*3', 'Intermediate Metabolizer'),
('NUDT15', '*1/*4', 'Possible Intermediate Metabolizer'),
('NUDT15', '*1/*5', 'Possible Intermediate Metabolizer'),
('NUDT15', '*1/*6', 'Intermediate Metabolizer'),
('NUDT15', '*2/*2', 'Poor Metabolizer'),
('NUDT15', '*2/*3', 'Poor Metabolizer'),
('NUDT15', '*3/*3', 'Intermediate Metabolizer');

-- Additional TPMT diplotype-to-phenotype mappings (supplements the JSON diplotype data)
INSERT INTO supplement_diplotypes (gene, diplotype, phenotype) VALUES
('TPMT', '*1/*1', 'Normal Metabolizer'),
('TPMT', '*1/*2', 'Intermediate Metabolizer'),
('TPMT', '*1/*3A', 'Intermediate Metabolizer'),
('TPMT', '*1/*3B', 'Intermediate Metabolizer'),
('TPMT', '*1/*3C', 'Intermediate Metabolizer'),
('TPMT', '*1/*4', 'Intermediate Metabolizer'),
('TPMT', '*1/*8', 'Intermediate Metabolizer'),
('TPMT', '*2/*2', 'Poor Metabolizer'),
('TPMT', '*2/*3A', 'Poor Metabolizer'),
('TPMT', '*3A/*3A', 'Poor Metabolizer'),
('TPMT', '*3A/*3C', 'Poor Metabolizer'),
('TPMT', '*3C/*3C', 'Poor Metabolizer');
