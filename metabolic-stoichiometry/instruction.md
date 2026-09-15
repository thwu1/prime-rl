A SQL dump at `/app/data/metabolic_dump.sql` defines a metabolic network with tables: `compounds` (id, name, formula), `reactions` (id, name, ec_number), `reaction_participants` (reaction_id, compound_id, coefficient, side), `compound_synonyms` (synonym_id, canonical_id), `pathways` (id, name), `pathway_reactions` (pathway_id, reaction_id, flux_coefficient). Side values are `'L'`/`'R'`. A KEGG compound reference is at `/app/data/compound_reference.dat`. Configuration at `/app/data/config.json`.

Some `reaction_participants.compound_id` values are synonym IDs resolvable through `compound_synonyms`. Some `compounds.formula` values are NULL, recoverable from the reference file.

Write `/app/Makefile` so `make -C /app all` produces eight files in `/app/results/`. Each output must be an individually buildable target (e.g., `make -C /app results/metabolic.db`) with correct prerequisite declarations ensuring dependency ordering.

**`results/metabolic.db`**: Corrected SQLite database: synonym references in `reaction_participants` replaced with canonical IDs; NULL formulas recovered for referenced compounds. Must also contain table `stoich_entries(reaction_id TEXT, compound_id TEXT, coefficient REAL)` populated with negative coefficients for left-side and positive for right-side participants, canonical compound IDs only.

**`results/data_recovery.json`**: `{compound_id: formula}` for each compound whose formula was NULL and is referenced by at least one reaction.

**`results/balance_report.json`**: `{reaction_id: {"balanced": bool, "element_deltas": {"ELEMENT": int}}}`. Deltas = left minus right atom counts across all elements.

**`results/pathway_stoichiometry.json`**: `{pathway_id: {"net_consumed": {compound_id: int}, "net_produced": {compound_id: int}, "element_balance": {"consistent": bool, "element_deltas": {"ELEMENT": int}}}}`. Positive flux = forward; negative = reversed. Net values positive integers; zero-net compounds excluded. Only non-zero element deltas included.

**`results/dead_ends.json`**: Sorted array of canonical compound IDs appearing in exactly one reaction.

**`results/chokepoints.json`**: Sorted array of reaction IDs with at least one dead-end participant.

**`results/shortest_paths.json`**: `"SOURCE->TARGET"` keys mapping to minimum reaction-hop distances. Currency metabolites from `config.json` excluded from traversal. -1 if unreachable. Query pairs from `config.json`.

**`results/stoichiometric_matrix.mtx`**: Stoichiometric matrix in Matrix Market coordinate format. Header line: `%%MatrixMarket matrix coordinate real general`. Rows = reactions sorted lexicographically by ID. Columns = compounds participating in at least one reaction (after synonym resolution), sorted lexicographically. Include comment lines `% ROWS: <space-separated IDs>` and `% COLS: <space-separated IDs>`. Data entries sorted by (row, col). Sign convention matches `stoich_entries`.

Success criteria:
- `make -C /app all` exits 0 and writes all eight files
- Individual make targets rebuild their prerequisites correctly
- Database has no synonym references, no NULL formulas for referenced compounds, and correct `stoich_entries`
- Element deltas correct at reaction and pathway levels
- Currency metabolites excluded from shortest-path computation
- Matrix Market file has correct format, dimensions, and coefficient values
