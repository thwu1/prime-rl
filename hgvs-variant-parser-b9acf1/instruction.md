Implement a Python package at `/app/hgvs_parser/` and a CLI tool at `/app/hgvs-tool` for HGVS sequence variant nomenclature processing. Create a Makefile at `/app/Makefile`. Reference data at `/app/data/`: `hgvs_grammar.txt` (PEG grammar), `amino_acids.json` (code mappings), `test_batch.tsv` (batch operations), `sample_variants.txt` (12 canonical variants).

**Python API** -- export from `/app/hgvs_parser/__init__.py`:

- `parse(s) -> object` -- Parse an HGVS string. Accessions may include an optional gene in parentheses: `NM_01234.5(GENE):c.65A>C`.
- `format_variant(parsed, conf=None) -> str` -- Format a parsed variant. Config keys: `p_3_letter` (bool, default True -- 3-letter amino acids; when False, use 1-letter codes and `*` for terminators), `p_term_asterisk` (bool, default False -- when True, replace `Ter` with `*`), `max_ref_length` (int|None, default 0 -- None preserves all ref bases; 0 strips all; N keeps ref if character length <= N).
- `roundtrip(s) -> str` -- `format_variant(parse(s))` with default config.
- `classify_edit(s) -> str` -- Return one of: `identity`, `sub`, `del`, `ins`, `delins`, `dup`, `inv`, `fs`, `ext`.
- `validate_grammar(rule, input_str) -> bool` -- Validate input against a named grammar rule. Required rules: `accn`, `dna`, `rna`, `aa1`, `aa3`, `aa13`, `term1`, `term3`, `term13`, `num`, `snum`, `hgvs_variant`, `g_variant`, `c_variant`, `p_variant`, `n_variant`, `m_variant`, `r_variant`.

**Canonical normalization** (default-config roundtrip behavior):

- Ref bases and numeric ref counts stripped from del/dup/identity (`delACT`->`del`, `dupT`->`dup`, `31T=`->`31=`, `del3`->`del`).
- Protein `*` normalized to `Ter` (`fs*10`->`fsTer10`, `ext*45`->`extTer45`).
- 1-letter amino acids normalized to 3-letter (`p.A3F`->`p.Ala3Phe`), including within insertions and delins.
- Frameshift without explicit stop codon appends `Ter` (`p.N1039fs`->`p.Asn1039fsTer`).
- Single-position `delXinsY` where ref and alt are each a single non-digit character normalizes to substitution (`c.76delAinsT`->`c.76A>T`).
- Multi-char or numeric ref in delins: ref stripped, remains delins (`c.76_77delAAinsC`->`c.76_77delinsC`, `c.76del5insT`->`c.76delinsT`).

Coordinate types: c, g, m, n, r, p. RNA preserves lowercase (`r.1a>u`). Intronic offsets (`c.88+1G>T`, `c.89-2A>C`), CDS_END datum (`c.*46T>A`), 5'UTR positions (`c.-14G>C`), protein extensions with negative length (`p.Met1Valext-10`), and protein interval operations (del, ins, delins, dup) must round-trip faithfully.

**CLI** -- executable at `/app/hgvs-tool` (`#!/usr/bin/env python3`, `chmod +x`):

- `parse`: stdin (one HGVS/line, skip blanks) -> JSON array. Elements: `{"input", "accession", "gene" (str|null), "type", "edit_type"}`.
- `classify`: stdin -> TSV: `<variant>\t<edit_type>`.
- `validate --rule RULE`: stdin -> JSON array: `[{"input", "valid"}, ...]`.
- `batch FILE`: TSV input (columns: `id`, `operation`, `input`; operations: `roundtrip`, `classify`, `validate:RULE`) -> JSON: `[{"id", "result"}, ...]`.
- `db load FILE --db PATH`: parse variants (one/line) into SQLite. Table: `variants(accession TEXT, gene TEXT, type TEXT, edit_type TEXT, raw TEXT, formatted TEXT)`.
- `db query --db PATH --sql SQL`: execute SQL, output JSON array of row-objects.

All CLI JSON output must be parseable by `jq` and composable in shell pipelines with `awk` and `sqlite3`.

**Makefile** -- `/app/Makefile`:

- `batch`: process `/app/data/test_batch.tsv` -> `/app/output/batch_results.json`.
- `db-create`: load `/app/data/sample_variants.txt` -> `/app/output/variants.db`.
- `db-stats`: query `/app/output/variants.db` for counts grouped by `type` (ORDER BY type ASC) -> `/app/output/db_stats.json`.
