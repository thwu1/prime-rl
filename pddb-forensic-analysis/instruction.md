A binary page table image from a Precursor device running the PDDB (Plausibly Deniable DataBase) filesystem requires a comprehensive security audit. The PDDB encrypts page table entries into independently-keyed "bases" — each unlocked by a name+password pair. Undiscovered bases are cryptographically indistinguishable from noise. The FSCB (Free Space Cache Block) caches only a subset of free pages.

All cryptographic parameters, binary format specifications, and key derivation details are documented in `/app/device_config.json`. Candidate credentials are provided.

## Inputs

- `/app/pddb_image.bin` — Binary page table dump
- `/app/device_config.json` — Cryptographic primitives, key derivation, and format specification
- `/app/passwords.txt` — Candidate passwords
- `/app/basis_names.txt` — Candidate basis names
- `/app/fscb.json` — Current FSCB snapshot
- `/app/fscb_previous.json` — Previous FSCB snapshot (captured before recent basis operations)

## Required Outputs (write to `/app/results/`)

**`bases.json`** — Object keyed by discovered basis name: `{"password": str, "key_hex": str, "num_entries": int}`

**`page_map.json`** — Object keyed by basis name: list of `{"physical_page": int, "virtual_address": int, "flags": int, "nonce": int}`

**`security_audit.json`** — A comprehensive security analysis of this PDDB deployment. The required output schema is specified in `/app/output_schema.json`.