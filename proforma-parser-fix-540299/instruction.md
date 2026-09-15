A Rust CLI at `/app/` parses HUPO-PSI ProForma 2.0 proteoform notation strings. Build with `cargo build --release --manifest-path /app/Cargo.toml`, then run `/app/target/release/proforma_parse /app/input.txt /app/output.json`.

The parser reads one ProForma string per line from the first argument (skipping empty and `#`-prefixed lines) and writes a JSON array to the second argument. The EBNF grammar at `/app/grammar.ebnf` is the authoritative specification for the notation.

The parser at `/app/src/parser.rs` is incomplete and contains defects. It handles basic sequences with inline modifications, terminal modifications, and integer charge states, but produces incorrect output or errors on valid inputs that use other ProForma 2.0 constructs. Some defects cause parse errors on valid input; others produce structurally valid output with incorrect field values.

Fix the parser so that all 36 positive inputs in `/app/input.txt` produce `"valid": true` with correct field values, and all 7 negative inputs produce `"valid": false`.

**Output per result:**

Valid: `{"input":"...","valid":true,"sequence":"...","chain_count":N,"ion_count":N,"charge":N or null,"modifications":[{"position":N,"value":"..."}],"n_terminal":[...],"c_terminal":[...],"features":[...]}`

Invalid: `{"input":"...","valid":false,"error":"..."}`

**Field semantics:**
- `sequence` — amino acid letters from the first chain of the first ion, including residues inside parenthesised regions
- `chain_count` — peptidoform chains in the first ion (separated by `//`)
- `ion_count` — chimeric ions (separated by `+`)
- `charge` — integer charge of first ion, or `null`; for adduct-ion charges, sum of z*occurrence for each carrier
- `modifications[].position` — 1-indexed within first-chain sequence
- `modifications[].value` — full text between outer `[` and its matching `]`; nested brackets preserved verbatim
- `n_terminal` / `c_terminal` — tag text for terminal modifications on the first chain
- `features` — sorted, deduplicated list drawn from: `"ambiguous_aa"`, `"charge"`, `"chimeric"`, `"cross_link"`, `"formula"`, `"global_fixed"`, `"global_isotope"`, `"glycan"`, `"info"`, `"label"`, `"labile"`, `"range"`, `"unlocalised"`
