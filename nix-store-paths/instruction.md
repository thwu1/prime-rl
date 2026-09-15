A simulated Nix binary cache at `/app/cache/` contains 16 `.narinfo` files representing cached Nix store paths. Some entries are valid; others have been corrupted — tampered store path hashes, undecodable content hashes, misclassified derivation types, or missing metadata fields.

Build an auditor that processes every `.narinfo` file, independently verifies each entry's integrity, and classifies its status. For each entry the auditor must recompute the expected Nix store path from the content-addressability (CA) metadata in the narinfo file, compare it against the claimed `StorePath`, and convert the content hash to all three encoding formats used in the Nix ecosystem (hexadecimal, Nix base-32, and SRI).

A previous engineer left a store path calculator at `/app/calculator.py` — it contains multiple bugs and produces incorrect results. The algorithm specifications are documented in `/app/spec.md` and `/app/reference.md`.

The output schema and status classifications are defined in `/app/schema.md`. Write the audit report to `/app/audit_report.json`.