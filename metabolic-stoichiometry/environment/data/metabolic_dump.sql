-- Normalized metabolic network database

CREATE TABLE compounds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    formula TEXT
);

CREATE TABLE reactions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ec_number TEXT
);

CREATE TABLE reaction_participants (
    reaction_id TEXT NOT NULL,
    compound_id TEXT NOT NULL,
    coefficient INTEGER NOT NULL DEFAULT 1,
    side TEXT NOT NULL CHECK(side IN ('L', 'R'))
);

CREATE TABLE compound_synonyms (
    synonym_id TEXT PRIMARY KEY,
    canonical_id TEXT NOT NULL
);

CREATE TABLE pathways (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE pathway_reactions (
    pathway_id TEXT NOT NULL,
    reaction_id TEXT NOT NULL,
    flux_coefficient INTEGER NOT NULL
);

-- Compounds (formula is NULL where recovery from reference file is needed)
INSERT INTO compounds VALUES ('C00001', 'H2O', 'H2O');
INSERT INTO compounds VALUES ('C00002', 'ATP', 'C10H16N5O13P3');
INSERT INTO compounds VALUES ('C00003', 'NAD+', 'C21H27N7O14P2');
INSERT INTO compounds VALUES ('C00004', 'NADH', 'C21H29N7O14P2');
INSERT INTO compounds VALUES ('C00005', 'NADPH', 'C21H30N7O17P3');
INSERT INTO compounds VALUES ('C00006', 'NADP+', 'C21H28N7O17P3');
INSERT INTO compounds VALUES ('C00008', 'ADP', 'C10H15N5O10P2');
INSERT INTO compounds VALUES ('C00009', 'Orthophosphate', 'H3O4P');
INSERT INTO compounds VALUES ('C00010', 'CoA', 'C21H36N7O16P3S');
INSERT INTO compounds VALUES ('C00011', 'CO2', 'CO2');
INSERT INTO compounds VALUES ('C00013', 'Diphosphate', 'H4O7P2');
INSERT INTO compounds VALUES ('C00014', 'Ammonia', 'H3N');
INSERT INTO compounds VALUES ('C00016', 'FAD', 'C27H33N9O15P2');
INSERT INTO compounds VALUES ('C00020', 'AMP', 'C10H14N5O7P');
INSERT INTO compounds VALUES ('C00022', 'Pyruvate', 'C3H4O3');
INSERT INTO compounds VALUES ('C00024', 'Acetyl-CoA', NULL);
INSERT INTO compounds VALUES ('C00025', 'L-Glutamate', 'C5H9NO4');
INSERT INTO compounds VALUES ('C00026', '2-Oxoglutarate', 'C5H6O5');
INSERT INTO compounds VALUES ('C00035', 'GDP', 'C10H15N5O11P2');
INSERT INTO compounds VALUES ('C00036', 'Oxaloacetate', 'C4H4O5');
INSERT INTO compounds VALUES ('C00041', 'L-Alanine', 'C3H7NO2');
INSERT INTO compounds VALUES ('C00042', 'Succinate', 'C4H6O4');
INSERT INTO compounds VALUES ('C00044', 'GTP', 'C10H16N5O14P3');
INSERT INTO compounds VALUES ('C00049', 'L-Aspartate', 'C4H7NO4');
INSERT INTO compounds VALUES ('C00074', 'Phosphoenolpyruvate', 'C3H5O6P');
INSERT INTO compounds VALUES ('C00080', 'H+', 'H');
INSERT INTO compounds VALUES ('C00085', 'D-Fructose 6-phosphate', 'C6H13O9P');
INSERT INTO compounds VALUES ('C00091', 'Succinyl-CoA', NULL);
INSERT INTO compounds VALUES ('C00111', 'Glycerone phosphate', 'C3H7O6P');
INSERT INTO compounds VALUES ('C00117', 'D-Ribose 5-phosphate', 'C5H11O8P');
INSERT INTO compounds VALUES ('C00118', 'D-Glyceraldehyde 3-phosphate', 'C3H7O6P');
INSERT INTO compounds VALUES ('C00122', 'Fumarate', 'C4H4O4');
INSERT INTO compounds VALUES ('C00149', '(S)-Malate', 'C4H6O5');
INSERT INTO compounds VALUES ('C00158', 'Citrate', 'C6H8O7');
INSERT INTO compounds VALUES ('C00197', '3-Phospho-D-glycerate', 'C3H7O7P');
INSERT INTO compounds VALUES ('C00199', 'D-Ribulose 5-phosphate', 'C5H11O8P');
INSERT INTO compounds VALUES ('C00231', 'D-Xylulose 5-phosphate', 'C5H11O8P');
INSERT INTO compounds VALUES ('C00236', '3-Phospho-D-glyceroyl phosphate', NULL);
INSERT INTO compounds VALUES ('C00267', 'alpha-D-Glucose', 'C6H12O6');
INSERT INTO compounds VALUES ('C00279', 'D-Erythrose 4-phosphate', 'C4H9O7P');
INSERT INTO compounds VALUES ('C00311', 'Isocitrate', 'C6H8O7');
INSERT INTO compounds VALUES ('C00345', '6-Phospho-D-gluconate', NULL);
INSERT INTO compounds VALUES ('C00354', 'D-Fructose 1,6-bisphosphate', NULL);
INSERT INTO compounds VALUES ('C00417', 'cis-Aconitate', 'C6H6O6');
INSERT INTO compounds VALUES ('C00631', '2-Phospho-D-glycerate', 'C3H7O7P');
INSERT INTO compounds VALUES ('C00668', 'alpha-D-Glucose 6-phosphate', 'C6H13O9P');
INSERT INTO compounds VALUES ('C01236', 'D-Glucono-1,5-lactone 6-phosphate', 'C6H11O9P');
INSERT INTO compounds VALUES ('C01352', 'FADH2', 'C27H35N9O15P2');
INSERT INTO compounds VALUES ('C05382', 'Sedoheptulose 7-phosphate', NULL);

-- Compound synonyms: alternate IDs used in some reaction_participants entries
INSERT INTO compound_synonyms VALUES ('C16238', 'C00024');
INSERT INTO compound_synonyms VALUES ('C05535', 'C00091');

-- Reactions
INSERT INTO reactions VALUES ('R01786', 'Hexokinase', '2.7.1.1');
INSERT INTO reactions VALUES ('R02739', 'Phosphoglucose isomerase', '5.3.1.9');
INSERT INTO reactions VALUES ('R00756', 'Phosphofructokinase', '2.7.1.11');
INSERT INTO reactions VALUES ('R01068', 'Fructose-bisphosphate aldolase', '4.1.2.13');
INSERT INTO reactions VALUES ('R01015', 'Triosephosphate isomerase', '5.3.1.1');
INSERT INTO reactions VALUES ('R01061', 'Glyceraldehyde-3-phosphate dehydrogenase', '1.2.1.12');
INSERT INTO reactions VALUES ('R01512', 'Phosphoglycerate kinase', '2.7.2.3');
INSERT INTO reactions VALUES ('R01662', 'Phosphoglycerate mutase', '5.4.2.11');
INSERT INTO reactions VALUES ('R00658', 'Enolase', '4.2.1.11');
INSERT INTO reactions VALUES ('R00200', 'Pyruvate kinase', '2.7.1.40');
INSERT INTO reactions VALUES ('R00209', 'Pyruvate dehydrogenase complex', '1.2.4.1');
INSERT INTO reactions VALUES ('R00351', 'Citrate synthase', '2.3.3.1');
INSERT INTO reactions VALUES ('R01325', 'Aconitase (citrate to cis-aconitate)', '4.2.1.3');
INSERT INTO reactions VALUES ('R01900', 'Aconitase (cis-aconitate to isocitrate)', '4.2.1.3');
INSERT INTO reactions VALUES ('R00709', 'Isocitrate dehydrogenase (NAD+)', '1.1.1.41');
INSERT INTO reactions VALUES ('R00621', '2-Oxoglutarate dehydrogenase complex', '1.2.4.2');
INSERT INTO reactions VALUES ('R00432', 'Succinyl-CoA synthetase (GDP-forming)', '6.2.1.4');
INSERT INTO reactions VALUES ('R02164', 'Succinate dehydrogenase', '1.3.5.1');
INSERT INTO reactions VALUES ('R01082', 'Fumarase', '4.2.1.2');
INSERT INTO reactions VALUES ('R00342', 'Malate dehydrogenase', '1.1.1.37');
INSERT INTO reactions VALUES ('R02736', 'Glucose-6-phosphate dehydrogenase', '1.1.1.49');
INSERT INTO reactions VALUES ('R02035', '6-Phosphogluconolactonase', '3.1.1.31');
INSERT INTO reactions VALUES ('R01528', '6-Phosphogluconate dehydrogenase', '1.1.1.44');
INSERT INTO reactions VALUES ('R01056', 'Ribulose-5-phosphate isomerase', '5.3.1.6');
INSERT INTO reactions VALUES ('R01529', 'Ribulose-5-phosphate 3-epimerase', '5.1.3.1');
INSERT INTO reactions VALUES ('R01641', 'Transketolase (reaction 1)', '2.2.1.1');
INSERT INTO reactions VALUES ('R01827', 'Transaldolase', '2.2.1.2');
INSERT INTO reactions VALUES ('R00258', 'Alanine aminotransferase', '2.6.1.2');
INSERT INTO reactions VALUES ('R00243', 'Glutamate dehydrogenase (NAD+)', '1.4.1.2');
INSERT INTO reactions VALUES ('R00355', 'Aspartate aminotransferase', '2.6.1.1');
INSERT INTO reactions VALUES ('R00004', 'Inorganic pyrophosphatase', '3.6.1.1');
INSERT INTO reactions VALUES ('RX0001', 'Erroneous isocitrate oxidoreductase (test entry)', '1.1.1.41');

-- Reaction participants
-- NOTE: Some entries use compound synonym IDs (C16238, C05535) instead of
-- canonical compound IDs. These must be resolved via compound_synonyms.

-- R01786: ATP + alpha-D-Glucose <=> ADP + alpha-D-Glucose 6-phosphate
INSERT INTO reaction_participants VALUES ('R01786', 'C00002', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01786', 'C00267', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01786', 'C00008', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01786', 'C00668', 1, 'R');

-- R02739: alpha-D-Glucose 6-phosphate <=> D-Fructose 6-phosphate
INSERT INTO reaction_participants VALUES ('R02739', 'C00668', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02739', 'C00085', 1, 'R');

-- R00756: ATP + D-Fructose 6-phosphate <=> ADP + D-Fructose 1,6-bisphosphate
INSERT INTO reaction_participants VALUES ('R00756', 'C00002', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00756', 'C00085', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00756', 'C00008', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00756', 'C00354', 1, 'R');

-- R01068: D-Fructose 1,6-bisphosphate <=> Glycerone phosphate + D-Glyceraldehyde 3-phosphate
INSERT INTO reaction_participants VALUES ('R01068', 'C00354', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01068', 'C00111', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01068', 'C00118', 1, 'R');

-- R01015: D-Glyceraldehyde 3-phosphate <=> Glycerone phosphate
INSERT INTO reaction_participants VALUES ('R01015', 'C00118', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01015', 'C00111', 1, 'R');

-- R01061: G3P + Pi + NAD+ <=> 1,3-BPG + NADH + H+
INSERT INTO reaction_participants VALUES ('R01061', 'C00118', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01061', 'C00009', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01061', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01061', 'C00236', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01061', 'C00004', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01061', 'C00080', 1, 'R');

-- R01512: ATP + 3-Phospho-D-glycerate <=> ADP + 3-Phospho-D-glyceroyl phosphate
INSERT INTO reaction_participants VALUES ('R01512', 'C00002', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01512', 'C00197', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01512', 'C00008', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01512', 'C00236', 1, 'R');

-- R01662: 3-Phospho-D-glycerate <=> 2-Phospho-D-glycerate
INSERT INTO reaction_participants VALUES ('R01662', 'C00197', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01662', 'C00631', 1, 'R');

-- R00658: 2-Phospho-D-glycerate <=> Phosphoenolpyruvate + H2O
INSERT INTO reaction_participants VALUES ('R00658', 'C00631', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00658', 'C00074', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00658', 'C00001', 1, 'R');

-- R00200: ATP + Pyruvate <=> ADP + Phosphoenolpyruvate
INSERT INTO reaction_participants VALUES ('R00200', 'C00002', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00200', 'C00022', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00200', 'C00008', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00200', 'C00074', 1, 'R');

-- R00209: Pyruvate + CoA + NAD+ <=> Acetyl-CoA + CO2 + NADH + H+
-- Uses synonym C16238 for Acetyl-CoA (C00024)
INSERT INTO reaction_participants VALUES ('R00209', 'C00022', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00209', 'C00010', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00209', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00209', 'C16238', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00209', 'C00011', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00209', 'C00004', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00209', 'C00080', 1, 'R');

-- R00351: Acetyl-CoA + Oxaloacetate + H2O <=> Citrate + CoA + H+
-- Uses synonym C16238 for Acetyl-CoA (C00024)
INSERT INTO reaction_participants VALUES ('R00351', 'C16238', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00351', 'C00036', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00351', 'C00001', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00351', 'C00158', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00351', 'C00010', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00351', 'C00080', 1, 'R');

-- R01325: Citrate <=> cis-Aconitate + H2O
INSERT INTO reaction_participants VALUES ('R01325', 'C00158', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01325', 'C00417', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01325', 'C00001', 1, 'R');

-- R01900: Isocitrate <=> cis-Aconitate + H2O
INSERT INTO reaction_participants VALUES ('R01900', 'C00311', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01900', 'C00417', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01900', 'C00001', 1, 'R');

-- R00709: Isocitrate + NAD+ <=> 2-Oxoglutarate + CO2 + NADH
INSERT INTO reaction_participants VALUES ('R00709', 'C00311', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00709', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00709', 'C00026', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00709', 'C00011', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00709', 'C00004', 1, 'R');

-- R00621: 2-Oxoglutarate + CoA + NAD+ <=> Succinyl-CoA + CO2 + NADH
-- Uses synonym C05535 for Succinyl-CoA (C00091)
INSERT INTO reaction_participants VALUES ('R00621', 'C00026', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00621', 'C00010', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00621', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00621', 'C05535', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00621', 'C00011', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00621', 'C00004', 1, 'R');

-- R00432: Succinyl-CoA + GDP + Pi <=> Succinate + CoA + GTP
-- Uses synonym C05535 for Succinyl-CoA (C00091)
INSERT INTO reaction_participants VALUES ('R00432', 'C05535', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00432', 'C00035', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00432', 'C00009', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00432', 'C00042', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00432', 'C00010', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00432', 'C00044', 1, 'R');

-- R02164: Succinate + FAD <=> Fumarate + FADH2
INSERT INTO reaction_participants VALUES ('R02164', 'C00042', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02164', 'C00016', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02164', 'C00122', 1, 'R');
INSERT INTO reaction_participants VALUES ('R02164', 'C01352', 1, 'R');

-- R01082: (S)-Malate <=> Fumarate + H2O
INSERT INTO reaction_participants VALUES ('R01082', 'C00149', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01082', 'C00122', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01082', 'C00001', 1, 'R');

-- R00342: (S)-Malate + NAD+ <=> Oxaloacetate + NADH + H+
INSERT INTO reaction_participants VALUES ('R00342', 'C00149', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00342', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00342', 'C00036', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00342', 'C00004', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00342', 'C00080', 1, 'R');

-- R02736: G6P + NADP+ <=> Gluconolactone-6P + NADPH + H+
INSERT INTO reaction_participants VALUES ('R02736', 'C00668', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02736', 'C00006', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02736', 'C01236', 1, 'R');
INSERT INTO reaction_participants VALUES ('R02736', 'C00005', 1, 'R');
INSERT INTO reaction_participants VALUES ('R02736', 'C00080', 1, 'R');

-- R02035: Gluconolactone-6P + H2O <=> 6-Phospho-D-gluconate
INSERT INTO reaction_participants VALUES ('R02035', 'C01236', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02035', 'C00001', 1, 'L');
INSERT INTO reaction_participants VALUES ('R02035', 'C00345', 1, 'R');

-- R01528: 6PG + NADP+ <=> Ru5P + CO2 + NADPH
INSERT INTO reaction_participants VALUES ('R01528', 'C00345', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01528', 'C00006', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01528', 'C00199', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01528', 'C00011', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01528', 'C00005', 1, 'R');

-- R01056: D-Ribulose 5-phosphate <=> D-Ribose 5-phosphate
INSERT INTO reaction_participants VALUES ('R01056', 'C00199', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01056', 'C00117', 1, 'R');

-- R01529: D-Ribulose 5-phosphate <=> D-Xylulose 5-phosphate
INSERT INTO reaction_participants VALUES ('R01529', 'C00199', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01529', 'C00231', 1, 'R');

-- R01641: Xu5P + R5P <=> Sed7P + G3P
INSERT INTO reaction_participants VALUES ('R01641', 'C00231', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01641', 'C00117', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01641', 'C05382', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01641', 'C00118', 1, 'R');

-- R01827: Sed7P + G3P <=> E4P + F6P
INSERT INTO reaction_participants VALUES ('R01827', 'C05382', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01827', 'C00118', 1, 'L');
INSERT INTO reaction_participants VALUES ('R01827', 'C00279', 1, 'R');
INSERT INTO reaction_participants VALUES ('R01827', 'C00085', 1, 'R');

-- R00258: L-Alanine + 2-Oxoglutarate <=> Pyruvate + L-Glutamate
INSERT INTO reaction_participants VALUES ('R00258', 'C00041', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00258', 'C00026', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00258', 'C00022', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00258', 'C00025', 1, 'R');

-- R00243: L-Glutamate + H2O + NAD+ <=> 2-OG + NH3 + NADH + H+
INSERT INTO reaction_participants VALUES ('R00243', 'C00025', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00243', 'C00001', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00243', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00243', 'C00026', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00243', 'C00014', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00243', 'C00004', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00243', 'C00080', 1, 'R');

-- R00355: L-Aspartate + 2-Oxoglutarate <=> Oxaloacetate + L-Glutamate
INSERT INTO reaction_participants VALUES ('R00355', 'C00049', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00355', 'C00026', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00355', 'C00036', 1, 'R');
INSERT INTO reaction_participants VALUES ('R00355', 'C00025', 1, 'R');

-- R00004: Diphosphate + H2O <=> 2 Orthophosphate
INSERT INTO reaction_participants VALUES ('R00004', 'C00013', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00004', 'C00001', 1, 'L');
INSERT INTO reaction_participants VALUES ('R00004', 'C00009', 2, 'R');

-- RX0001: Isocitrate + NAD+ <=> 2-Oxoglutarate + NADH (deliberately unbalanced)
INSERT INTO reaction_participants VALUES ('RX0001', 'C00311', 1, 'L');
INSERT INTO reaction_participants VALUES ('RX0001', 'C00003', 1, 'L');
INSERT INTO reaction_participants VALUES ('RX0001', 'C00026', 1, 'R');
INSERT INTO reaction_participants VALUES ('RX0001', 'C00004', 1, 'R');

-- Pathways
INSERT INTO pathways VALUES ('PWY-GLY', 'Glycolysis (Embden-Meyerhof pathway)');
INSERT INTO pathways VALUES ('PWY-TCA', 'Citrate cycle (TCA cycle)');
INSERT INTO pathways VALUES ('PWY-PPP', 'Pentose phosphate pathway (oxidative branch)');
INSERT INTO pathways VALUES ('PWY-PDH', 'Pyruvate oxidation');
INSERT INTO pathways VALUES ('PWY-AA', 'Amino acid transamination');

-- Pathway reactions (flux_coefficient: positive=forward, negative=reversed)
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01786', 1);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R02739', 1);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R00756', 1);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01068', 1);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01015', -1);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01061', 2);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01512', -2);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R01662', 2);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R00658', 2);
INSERT INTO pathway_reactions VALUES ('PWY-GLY', 'R00200', -2);

INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R00351', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R01325', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R01900', -1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R00709', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R00621', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R00432', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R02164', 1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R01082', -1);
INSERT INTO pathway_reactions VALUES ('PWY-TCA', 'R00342', 1);

INSERT INTO pathway_reactions VALUES ('PWY-PPP', 'R02736', 1);
INSERT INTO pathway_reactions VALUES ('PWY-PPP', 'R02035', 1);
INSERT INTO pathway_reactions VALUES ('PWY-PPP', 'R01528', 1);

INSERT INTO pathway_reactions VALUES ('PWY-PDH', 'R00209', 1);

INSERT INTO pathway_reactions VALUES ('PWY-AA', 'R00258', 1);
INSERT INTO pathway_reactions VALUES ('PWY-AA', 'R00355', 1);
