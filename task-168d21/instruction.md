A dataset from the constructed agglutinative language "Kaltiru" is provided at `/app/data/`. The language features complex morphophonological interactions including vowel harmony, consonant alternations conditioned by phonological context, and suffix allomorphy.

**Files:**
- `/app/data/training.tsv` — 125 word forms with morphological glosses (tab-separated: `surface_form\tgloss`)
- `/app/data/roots.tsv` — 20 root words and their English meanings (tab-separated: `root\tmeaning`)
- `/app/data/test_glosses.txt` — 43 morphological glosses for which you must generate correct surface forms

**Gloss notation:**
- Morphological components are dot-separated: `meaning[.PL][.possessive][.case]`
- `PL` = plural
- `1SG`, `2SG`, `3SG` = 1st/2nd/3rd person singular possessive
- `1PL`, `2PL`, `3PL` = 1st/2nd/3rd person plural possessive
- `ACC` = accusative, `GEN` = genitive, `DAT` = dative, `LOC` = locative, `ABL` = ablative
- Forms with no case label are nominative

Analyze the training data to discover all morphological rules and phonological processes operating in this language. Build a **morphological generator as a compiled HFST finite-state transducer**. The HFST toolkit (`hfst-strings2fst`, `hfst-minimize`, `hfst-lookup`, `hfst-lexc`, etc.) is pre-installed.

**Required outputs:**
- `/app/kaltiru.hfst` — compiled HFST transducer that maps glosses to surface forms (must work with `hfst-lookup`)
- `/app/kaltiru.lexc` — LEXC grammar file describing the morphotactic structure of Kaltiru (must compile with `hfst-lexc`)
- `/app/Makefile` — build pipeline that orchestrates transducer compilation and form generation
- `/app/output.txt` — one surface form per line, matching the order of glosses in `/app/data/test_glosses.txt`

The entire build (transducer compilation + output generation) must be reproducible via `make all` in `/app/`. All 43 forms must be correct.