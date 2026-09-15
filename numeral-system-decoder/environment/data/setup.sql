-- Vorathi Language Family Fieldwork Database
-- Contains lexical data, field observations, training examples, and test cases

CREATE TABLE lexicon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    surface_form TEXT NOT NULL,
    entry_data TEXT NOT NULL
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector TEXT NOT NULL,
    language TEXT NOT NULL,
    date TEXT NOT NULL,
    obs_type TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE training (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    number INTEGER NOT NULL,
    word_form TEXT NOT NULL,
    collector TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'high'
);

CREATE TABLE test_decode (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    word_form TEXT NOT NULL
);

CREATE TABLE test_encode (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    number INTEGER NOT NULL
);

CREATE TABLE test_cross (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_language TEXT NOT NULL,
    source_word TEXT NOT NULL,
    target_language TEXT NOT NULL
);

-- ═══════════════════════════════════════════════════════════════
-- Lexicon entries (numeral morphemes + general vocabulary)
-- Entry data stored as JSON blobs
-- ═══════════════════════════════════════════════════════════════

-- Turahi lexicon
INSERT INTO lexicon (language, surface_form, entry_data) VALUES
('turahi', 'dalo', '{"gloss": "to eat", "domain": "basic_verb", "pos": "verb"}'),
('turahi', 'duma', '{"gloss": "thank you", "domain": "courtesy", "pos": "intj"}'),
('turahi', 'dun', '{"value": 8, "domain": "numeral", "pos": "num"}'),
('turahi', 'fi', '{"value": 2, "domain": "numeral", "pos": "num"}'),
('turahi', 'fiso', '{"gloss": "big", "domain": "descriptive", "pos": "adj"}'),
('turahi', 'ke', '{"value": 4, "domain": "numeral", "pos": "num"}'),
('turahi', 'kori', '{"gloss": "fire", "domain": "natural_element", "pos": "noun"}'),
('turahi', 'la', '{"value": 6, "domain": "numeral", "pos": "num"}'),
('turahi', 'lori', '{"gloss": "hello", "domain": "greeting", "pos": "intj"}'),
('turahi', 'mava', '{"gloss": "mother", "domain": "kinship", "pos": "noun"}'),
('turahi', 'mu', '{"value": 5, "domain": "numeral", "pos": "num"}'),
('turahi', 'muri', '{"gloss": "to sleep", "domain": "basic_verb", "pos": "verb"}'),
('turahi', 'na', '{"value": 1, "domain": "numeral", "pos": "num"}'),
('turahi', 'nako', '{"gloss": "here", "domain": "spatial", "pos": "adv"}'),
('turahi', 'palu', '{"gloss": "there", "domain": "spatial", "pos": "adv"}'),
('turahi', 'pari', '{"gloss": "father", "domain": "kinship", "pos": "noun"}'),
('turahi', 'po', '{"value": 7, "domain": "numeral", "pos": "num"}'),
('turahi', 'ram', '{"value": 64, "domain": "numeral", "pos": "num"}'),
('turahi', 'so', '{"value": 3, "domain": "numeral", "pos": "num"}'),
('turahi', 'suno', '{"gloss": "water", "domain": "natural_element", "pos": "noun"}'),
('turahi', 'vana', '{"gloss": "good", "domain": "descriptive", "pos": "adj"}'),
('turahi', 'vol', '{"value": 512, "domain": "numeral", "pos": "num"}');

-- Belago lexicon
INSERT INTO lexicon (language, surface_form, entry_data) VALUES
('belago', 'bokam', '{"gloss": "big", "domain": "descriptive", "pos": "adj"}'),
('belago', 'bor', '{"value": 400, "domain": "numeral", "pos": "num"}'),
('belago', 'buri', '{"gloss": "father", "domain": "kinship", "pos": "noun"}'),
('belago', 'cha', '{"value": 1, "domain": "numeral", "pos": "num"}'),
('belago', 'chido', '{"gloss": "to eat", "domain": "basic_verb", "pos": "verb"}'),
('belago', 'doi', '{"value": 2, "domain": "numeral", "pos": "num"}'),
('belago', 'kal', '{"value": 20, "domain": "numeral", "pos": "num"}'),
('belago', 'kaldo', '{"gloss": "there", "domain": "spatial", "pos": "adv"}'),
('belago', 'kunen', '{"gloss": "water", "domain": "natural_element", "pos": "noun"}'),
('belago', 'mako', '{"gloss": "mother", "domain": "kinship", "pos": "noun"}'),
('belago', 'nela', '{"gloss": "good", "domain": "descriptive", "pos": "adj"}'),
('belago', 'nen', '{"value": 5, "domain": "numeral", "pos": "num"}'),
('belago', 'nimba', '{"gloss": "hello", "domain": "greeting", "pos": "intj"}'),
('belago', 'pak', '{"value": 4, "domain": "numeral", "pos": "num"}'),
('belago', 'pakin', '{"gloss": "to sleep", "domain": "basic_verb", "pos": "verb"}'),
('belago', 'talem', '{"gloss": "fire", "domain": "natural_element", "pos": "noun"}'),
('belago', 'telin', '{"gloss": "thank you", "domain": "courtesy", "pos": "intj"}'),
('belago', 'tin', '{"value": 3, "domain": "numeral", "pos": "num"}'),
('belago', 'tucha', '{"gloss": "here", "domain": "spatial", "pos": "adv"}'),
('belago', 'tum', '{"value": 10, "domain": "numeral", "pos": "num"}');

-- Renshi lexicon
INSERT INTO lexicon (language, surface_form, entry_data) VALUES
('renshi', 'ama', '{"gloss": "mother", "domain": "kinship", "pos": "noun"}'),
('renshi', 'bapa', '{"gloss": "father", "domain": "kinship", "pos": "noun"}'),
('renshi', 'dwa', '{"value": 2, "domain": "numeral", "pos": "num"}'),
('renshi', 'dwama', '{"gloss": "hello", "domain": "greeting", "pos": "intj"}'),
('renshi', 'ek', '{"value": 1, "domain": "numeral", "pos": "num"}'),
('renshi', 'ekda', '{"gloss": "here", "domain": "spatial", "pos": "adv"}'),
('renshi', 'fedwa', '{"value": 10, "domain": "numeral", "pos": "num"}'),
('renshi', 'feek', '{"value": 11, "domain": "numeral", "pos": "num"}'),
('renshi', 'fekat', '{"value": 8, "domain": "numeral", "pos": "num"}'),
('renshi', 'fetri', '{"value": 9, "domain": "numeral", "pos": "num"}'),
('renshi', 'gara', '{"gloss": "fire", "domain": "natural_element", "pos": "noun"}'),
('renshi', 'gros', '{"value": 144, "domain": "numeral", "pos": "num"}'),
('renshi', 'hepan', '{"gloss": "to sleep", "domain": "basic_verb", "pos": "verb"}'),
('renshi', 'hes', '{"value": 6, "domain": "numeral", "pos": "num"}'),
('renshi', 'hesta', '{"gloss": "thank you", "domain": "courtesy", "pos": "intj"}'),
('renshi', 'kasep', '{"gloss": "big", "domain": "descriptive", "pos": "adj"}'),
('renshi', 'kat', '{"value": 4, "domain": "numeral", "pos": "num"}'),
('renshi', 'nekat', '{"gloss": "to eat", "domain": "basic_verb", "pos": "verb"}'),
('renshi', 'pen', '{"value": 5, "domain": "numeral", "pos": "num"}'),
('renshi', 'sep', '{"value": 7, "domain": "numeral", "pos": "num"}'),
('renshi', 'sura', '{"gloss": "water", "domain": "natural_element", "pos": "noun"}'),
('renshi', 'tri', '{"value": 3, "domain": "numeral", "pos": "num"}'),
('renshi', 'trisa', '{"gloss": "good", "domain": "descriptive", "pos": "adj"}'),
('renshi', 'zan', '{"value": 12, "domain": "numeral", "pos": "num"}'),
('renshi', 'zanpir', '{"gloss": "there", "domain": "spatial", "pos": "adv"}');

-- ═══════════════════════════════════════════════════════════════
-- Field observations
-- ═══════════════════════════════════════════════════════════════

INSERT INTO observations (collector, language, date, obs_type, content) VALUES
('dr_amara', 'turahi', '2024-03-15', 'phonological', 'No tone distinctions observed in Turahi. Stress appears fixed on the penultimate syllable in polysyllabic words.'),
('dr_amara', 'turahi', '2024-03-15', 'cultural', 'Turahi counting is performed using small river stones. Informant groups stones into piles of consistent size before counting the piles.'),
('dr_amara', 'turahi', '2024-03-16', 'morphological', 'Turahi number expressions appear to be composed of discrete word-tokens with clear audible boundaries. No assimilation or elision observed between adjacent tokens.'),
('dr_amara', 'turahi', '2024-03-16', 'numeral', 'The token ''dun'' seems to demarcate a significant numerical boundary. Informant began using it consistently once basic digit words were exhausted.'),
('dr_amara', 'turahi', '2024-03-17', 'cultural', 'Informant described ''ram'' as corresponding to a traditional basket-load of fruit. The relationship between ''dun'' and ''ram'' appears to follow the same scaling pattern as between individual items and ''dun''.'),
('dr_amara', 'turahi', '2024-03-17', 'numeral', 'The token ''vol'' was elicited only for very large quantities. Informant indicated it represents many basket-loads, following the same hierarchical pattern.'),
('dr_amara', 'turahi', '2024-03-17', 'numeral', 'Attempted to elicit a word for zero but informant stated the concept does not exist. One simply says nothing when there is nothing to count.'),
('dr_amara', 'belago', '2024-03-18', 'phonological', 'Belago syllable structure is consistently CV or CVC. No consonant clusters observed in any position.'),
('dr_amara', 'belago', '2024-03-18', 'cultural', 'Belago market traders use bundled items as standard units. The word ''kal'' appears in trading contexts when referring to standard bundles.'),
('dr_amara', 'belago', '2024-03-19', 'numeral', 'Belago number expressions have a layered structure with specific tokens separating counting tiers.'),
('dr_amara', 'belago', '2024-03-19', 'numeral', 'The token ''bor'' represents a higher-order grouping. Informant demonstrated by arranging multiple piles of bundles and sweeping them together.'),
('dr_amara', 'belago', '2024-03-20', 'cultural', 'Belago uses noun classifiers for counting different types of objects, but the numeral roots remain the same regardless of classifier.'),
('dr_amara', 'renshi', '2024-03-21', 'phonological', 'Renshi permits onset consonant clusters, unlike Turahi and Belago. Stress falls on the first syllable.'),
('dr_amara', 'renshi', '2024-03-21', 'morphological', 'The prefix ''fe-'' is productive in Renshi morphology. It appears in both numeral and non-numeral word classes with related but distinct semantic functions.'),
('dr_amara', 'renshi', '2024-03-22', 'numeral', 'Informant confirmed that ''fekat'' and ''kat'' are related. Described ''fekat'' as representing what remains to complete a full group after ''kat'' items have been placed.'),
('dr_amara', 'renshi', '2024-03-22', 'numeral', 'Renshi speakers associate their primary grouping unit with natural cycles. The informant referenced lunar observations when explaining the grouping size.'),
('dr_amara', 'renshi', '2024-03-23', 'numeral', 'The term ''gros'' represents a higher-order grouping that the informant described as a complete collection of complete groups.'),
('asst_belo', 'turahi', '2024-03-16', 'logistical', 'Battery in recording device low. Switched to manual notation for remainder of session.'),
('asst_belo', 'turahi', '2024-03-17', 'numeral', 'Verified Turahi digit tokens with second informant. All seven basic counting words confirmed with consistent values.'),
('asst_belo', 'belago', '2024-03-19', 'logistical', 'Rain delayed fieldwork. Relocated to village elder''s home for afternoon session.'),
('asst_belo', 'belago', '2024-03-20', 'numeral', 'Within Belago counting tiers, the tokens ''nen'' and ''tum'' appear to function as intermediate grouping markers that compose additively with the basic digit tokens.'),
('asst_belo', 'renshi', '2024-03-22', 'numeral', 'Renshi compound numerals follow a structural pattern where the position of a token relative to a grouping word determines the arithmetic relationship between them.'),
('asst_belo', 'renshi', '2024-03-23', 'morphological', 'The ''fe-'' prefix in Renshi numerals systematically derives forms from the basic digit words. The derived values appear to have a regular mathematical relationship to their base forms.'),
('asst_belo', 'general', '2024-03-24', 'comparative', 'All three Vorathi family numeral systems share the principle that compound expressions are ordered from larger to smaller components.'),
('asst_belo', 'general', '2024-03-24', 'logistical', 'Follow-up session needed to verify counting in the hundreds and thousands range for all three languages.'),
('asst_belo', 'general', '2024-03-25', 'comparative', 'Despite different grouping sizes, all three systems use a layered structure with named tokens for significant quantity thresholds.');

-- ═══════════════════════════════════════════════════════════════
-- Training data
-- Note: some entries contain transcription errors
-- ═══════════════════════════════════════════════════════════════

-- Turahi training (IDs 1-36)
INSERT INTO training (language, number, word_form, collector, confidence) VALUES
('turahi', 1, 'na', 'dr_amara', 'high'),
('turahi', 2, 'fi', 'dr_amara', 'high'),
('turahi', 3, 'so', 'dr_amara', 'high'),
('turahi', 4, 'ke', 'dr_amara', 'high'),
('turahi', 5, 'mu', 'dr_amara', 'high'),
('turahi', 6, 'la', 'dr_amara', 'high'),
('turahi', 7, 'po', 'dr_amara', 'high'),
('turahi', 8, 'dun', 'dr_amara', 'high'),
('turahi', 9, 'dun na', 'dr_amara', 'high'),
('turahi', 11, 'dun so', 'dr_amara', 'medium'),
('turahi', 14, 'dun la', 'asst_belo', 'high'),
('turahi', 16, 'fi dun', 'asst_belo', 'high'),
('turahi', 21, 'fi dun mu', 'asst_belo', 'high'),
('turahi', 24, 'so dun', 'asst_belo', 'high'),
('turahi', 30, 'so dun la', 'asst_belo', 'high'),
('turahi', 32, 'ke dun', 'asst_belo', 'high'),
('turahi', 40, 'mu dun', 'asst_belo', 'high'),
('turahi', 48, 'la dun', 'asst_belo', 'high'),
('turahi', 56, 'po dun', 'dr_amara', 'high'),
('turahi', 63, 'po dun po', 'dr_amara', 'high'),
('turahi', 64, 'ram', 'dr_amara', 'high'),
('turahi', 65, 'ram na', 'dr_amara', 'high'),
('turahi', 72, 'ram dun', 'dr_amara', 'high'),
('turahi', 80, 'ram dun fi', 'dr_amara', 'high'),
('turahi', 100, 'ram ke dun ke', 'asst_belo', 'high'),
('turahi', 128, 'fi ram', 'asst_belo', 'high'),
('turahi', 192, 'so ram', 'asst_belo', 'medium'),
('turahi', 200, 'so ram na', 'asst_belo', 'medium'),
('turahi', 256, 'ke ram', 'dr_amara', 'high'),
('turahi', 320, 'mu ram', 'dr_amara', 'high'),
('turahi', 384, 'la ram', 'dr_amara', 'high'),
('turahi', 448, 'po ram', 'dr_amara', 'high'),
('turahi', 500, 'po ram mu dun ke', 'dr_amara', 'high'),
('turahi', 512, 'vol', 'dr_amara', 'high'),
('turahi', 520, 'vol dun', 'asst_belo', 'high'),
('turahi', 576, 'vol ram', 'asst_belo', 'high');

-- Belago training (IDs 37-75)
INSERT INTO training (language, number, word_form, collector, confidence) VALUES
('belago', 1, 'cha', 'dr_amara', 'high'),
('belago', 2, 'doi', 'dr_amara', 'high'),
('belago', 3, 'tin', 'dr_amara', 'high'),
('belago', 4, 'pak', 'dr_amara', 'high'),
('belago', 5, 'nen', 'dr_amara', 'high'),
('belago', 6, 'nen cha', 'dr_amara', 'high'),
('belago', 7, 'nen doi', 'dr_amara', 'high'),
('belago', 8, 'nen tin', 'asst_belo', 'high'),
('belago', 9, 'nen pak', 'asst_belo', 'high'),
('belago', 10, 'tum', 'asst_belo', 'high'),
('belago', 11, 'tum cha', 'asst_belo', 'high'),
('belago', 13, 'tum tin', 'asst_belo', 'high'),
('belago', 15, 'tum nen', 'asst_belo', 'high'),
('belago', 17, 'tum nen doi', 'dr_amara', 'medium'),
('belago', 19, 'tum nen pak', 'dr_amara', 'high'),
('belago', 20, 'kal', 'dr_amara', 'high'),
('belago', 21, 'kal cha', 'dr_amara', 'high'),
('belago', 25, 'kal nen', 'dr_amara', 'high'),
('belago', 30, 'kal tum', 'asst_belo', 'high'),
('belago', 33, 'kal tum doi', 'asst_belo', 'high'),
('belago', 38, 'kal tum nen tin', 'asst_belo', 'high'),
('belago', 40, 'doi kal', 'asst_belo', 'high'),
('belago', 42, 'doi kal doi', 'asst_belo', 'high'),
('belago', 55, 'doi kal tum nen', 'dr_amara', 'high'),
('belago', 60, 'tin kal', 'dr_amara', 'high'),
('belago', 80, 'pak kal', 'dr_amara', 'high'),
('belago', 99, 'pak kal tum nen pak', 'dr_amara', 'high'),
('belago', 100, 'nen kal', 'dr_amara', 'high'),
('belago', 120, 'nen doi kal', 'dr_amara', 'medium'),
('belago', 200, 'tum kal', 'asst_belo', 'high'),
('belago', 300, 'tum nen kal', 'asst_belo', 'high'),
('belago', 399, 'tum nen pak kal tum nen pak', 'asst_belo', 'high'),
('belago', 400, 'bor', 'asst_belo', 'high'),
('belago', 420, 'bor kal', 'asst_belo', 'high'),
('belago', 500, 'bor nen kal', 'dr_amara', 'high'),
('belago', 800, 'tin bor', 'asst_belo', 'high'),
('belago', 1000, 'doi bor tum kal', 'dr_amara', 'high'),
('belago', 2000, 'nen bor', 'dr_amara', 'high'),
('belago', 3000, 'nen doi bor tum kal', 'dr_amara', 'high');

-- Renshi training (IDs 76-115)
INSERT INTO training (language, number, word_form, collector, confidence) VALUES
('renshi', 1, 'ek', 'dr_amara', 'high'),
('renshi', 2, 'dwa', 'dr_amara', 'high'),
('renshi', 3, 'tri', 'dr_amara', 'high'),
('renshi', 4, 'kat', 'dr_amara', 'high'),
('renshi', 5, 'pen', 'dr_amara', 'high'),
('renshi', 6, 'hes', 'dr_amara', 'high'),
('renshi', 7, 'sep', 'dr_amara', 'high'),
('renshi', 8, 'fekat', 'asst_belo', 'high'),
('renshi', 9, 'fetri', 'asst_belo', 'high'),
('renshi', 10, 'fedwa', 'asst_belo', 'high'),
('renshi', 11, 'feek', 'asst_belo', 'high'),
('renshi', 12, 'zan', 'asst_belo', 'high'),
('renshi', 13, 'zan ek', 'asst_belo', 'high'),
('renshi', 15, 'zan tri', 'asst_belo', 'high'),
('renshi', 18, 'zan hes', 'dr_amara', 'high'),
('renshi', 20, 'zan fekat', 'dr_amara', 'high'),
('renshi', 23, 'zan feek', 'dr_amara', 'high'),
('renshi', 24, 'dwa zan', 'dr_amara', 'high'),
('renshi', 30, 'dwa zan hes', 'dr_amara', 'medium'),
('renshi', 36, 'tri zan', 'asst_belo', 'high'),
('renshi', 48, 'kat zan', 'asst_belo', 'high'),
('renshi', 60, 'pen zan', 'asst_belo', 'high'),
('renshi', 72, 'hes zan ek', 'dr_amara', 'high'),
('renshi', 84, 'sep zan', 'dr_amara', 'high'),
('renshi', 96, 'fekat zan', 'dr_amara', 'high'),
('renshi', 100, 'fekat zan kat', 'dr_amara', 'high'),
('renshi', 108, 'fetri zan', 'asst_belo', 'high'),
('renshi', 120, 'fedwa zan', 'asst_belo', 'high'),
('renshi', 132, 'feek zan', 'asst_belo', 'high'),
('renshi', 143, 'feek zan feek', 'asst_belo', 'high'),
('renshi', 144, 'gros', 'asst_belo', 'high'),
('renshi', 145, 'gros ek', 'asst_belo', 'high'),
('renshi', 156, 'gros zan', 'dr_amara', 'high'),
('renshi', 168, 'gros dwa zan', 'dr_amara', 'high'),
('renshi', 200, 'gros kat zan fekat', 'dr_amara', 'high'),
('renshi', 288, 'dwa gros', 'dr_amara', 'high'),
('renshi', 300, 'dwa gros zan', 'dr_amara', 'medium'),
('renshi', 432, 'tri gros', 'asst_belo', 'high'),
('renshi', 500, 'tri gros pen zan fekat', 'asst_belo', 'high'),
('renshi', 1000, 'hes gros feek zan pen', 'asst_belo', 'medium');

-- ═══════════════════════════════════════════════════════════════
-- Test cases
-- ═══════════════════════════════════════════════════════════════

-- Decode tests
INSERT INTO test_decode (language, word_form) VALUES
('turahi', 'dun fi'),
('turahi', 'fi dun so'),
('turahi', 'ke dun fi'),
('turahi', 'la dun so'),
('turahi', 'fi ram la'),
('turahi', 'so ram dun po'),
('turahi', 'ke ram so dun fi'),
('turahi', 'mu ram po dun so'),
('turahi', 'la ram ke dun mu'),
('turahi', 'vol mu dun ke'),
('turahi', 'vol so ram fi dun na'),
('turahi', 'fi vol ke ram so dun po');

INSERT INTO test_decode (language, word_form) VALUES
('belago', 'tum doi'),
('belago', 'nen tin kal'),
('belago', 'tin kal nen doi'),
('belago', 'nen pak kal tum tin'),
('belago', 'tum cha kal nen pak'),
('belago', 'tum nen tin kal nen'),
('belago', 'bor doi kal tin'),
('belago', 'bor tum nen pak kal tum nen pak'),
('belago', 'tin bor nen kal tum doi'),
('belago', 'pak bor tum nen doi kal nen pak'),
('belago', 'nen bor kal tum nen pak'),
('belago', 'tum bor tum nen pak kal tum doi');

INSERT INTO test_decode (language, word_form) VALUES
('renshi', 'zan dwa'),
('renshi', 'zan sep'),
('renshi', 'zan fedwa'),
('renshi', 'tri zan pen'),
('renshi', 'pen zan dwa'),
('renshi', 'sep zan fetri'),
('renshi', 'feek zan sep'),
('renshi', 'gros tri'),
('renshi', 'gros hes zan pen'),
('renshi', 'dwa gros sep zan fetri'),
('renshi', 'kat gros fekat zan tri'),
('renshi', 'sep gros feek zan feek');

-- Encode tests
INSERT INTO test_encode (language, number) VALUES
('turahi', 13),
('turahi', 27),
('turahi', 45),
('turahi', 99),
('turahi', 150),
('turahi', 250),
('turahi', 333),
('turahi', 400),
('turahi', 511),
('turahi', 1000);

INSERT INTO test_encode (language, number) VALUES
('belago', 14),
('belago', 37),
('belago', 76),
('belago', 123),
('belago', 256),
('belago', 350),
('belago', 444),
('belago', 750),
('belago', 1500),
('belago', 5555);

INSERT INTO test_encode (language, number) VALUES
('renshi', 16),
('renshi', 35),
('renshi', 50),
('renshi', 77),
('renshi', 111),
('renshi', 130),
('renshi', 201),
('renshi', 333),
('renshi', 501),
('renshi', 999);

-- Cross-system translation tests
INSERT INTO test_cross (source_language, source_word, target_language) VALUES
('turahi', 'la ram ke dun', 'belago'),
('belago', 'tin kal nen tin', 'renshi'),
('renshi', 'dwa gros kat zan', 'turahi'),
('turahi', 'vol fi ram so dun la', 'belago'),
('renshi', 'pen gros sep zan pen', 'belago');
