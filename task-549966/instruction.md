The Library of Congress BagIt conformance test suite is at `/app/conformance-suite/`, containing ~60 bags organized by spec version (`v0.93` through `v1.0`) and expected outcome (`valid/`, `invalid/`, `warning/`, `linux-only/`, `windows-only/`). RFC 8493 is at `/app/rfc8493.txt`.

Four damaged serialized BagIt bags are at `/app/damaged-archives/` (`.tar.gz`). Each was a valid bag before suffering one or more forms of corruption spanning encoding damage, checksum corruption, path-security violations, structural defects, serialization errors, metadata formatting issues, and manifest completeness failures.

Produce three artifacts:

## 1. `/app/bagit-validate`

An executable taking a single bag directory path argument. Must exit 0 for valid bags and non-zero for invalid. It must correctly classify every bag in the conformance suite: `valid/` and platform-independent `warning/` bags exit 0; `invalid/` and `linux-only/` bags exit non-zero. Filesystem-dependent warning bags (`duplicate-file-with-different-case`, `same-filename-listed-twice-with-different-normalization`, `special-system-files`) may exit either way. `windows-only/` bags are skipped.

## 2. `/app/repaired-archives/`

For each `.tar.gz` in `/app/damaged-archives/`, extract it, diagnose all RFC 8493 violations, repair the bag to full v1.0 compliance, and re-serialize as a `.tar.gz` here. Each repaired archive must use correct BagIt serialization structure (single top-level directory whose name matches the archive base name). Repaired bags must have `BagIt-Version: 1.0` with `Tag-File-Character-Encoding: UTF-8` and no BOM, correct checksums verified against actual payload content, every payload file in every manifest (v1.0 completeness rule), and no path-traversal entries, duplicate manifest entries, or metadata formatting violations.

## 3. `/app/forensic-report.json`

A JSON object mapping each damaged archive's base name (without `.tar.gz`) to a list of violation categories from this taxonomy:

- `"checksum"` — payload/tag checksum mismatch, or duplicate entries with conflicting hashes
- `"completeness"` — payload files absent from manifests, or manifests listing different file sets
- `"encoding"` — BOM in bagit.txt
- `"structure"` — missing/malformed version or encoding declaration
- `"path-security"` — path traversal in manifests or fetch.txt
- `"serialization"` — incorrect archive structure (no proper top-level bag directory)
- `"metadata"` — whitespace before colon in tag file labels

All four archives must appear as keys with at least one accurate violation category each.

## Constraints

- The conformance suite at `/app/conformance-suite/` must remain intact with at least `v0.97` and `v1.0` directories preserved.
- No existing BagIt libraries may be used — implement validation and repair from scratch using only the RFC and standard library capabilities (plus hashlib or equivalent).