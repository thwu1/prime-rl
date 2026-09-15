A corpus of ANSI/NIST-ITL 1-2011 biometric transaction files (traditional encoding) is at `/app/corpus/`. The encoding specification is at `/app/spec.txt`. An HMAC signing key is at `/app/hmac.key`.

Some corpus files are conforming; others contain violations. Build `/app/toolkit.py` that, when run as `python3 /app/toolkit.py`, processes every `.an2k` file in `/app/corpus/` and produces:

- `/app/report.json` — maps each filename (string key) to its sorted, deduplicated list of violation code strings
- `/app/reconstructed/` — repaired copy of each corpus file; every reconstructed file must pass validation with zero violations; files that were already valid must be byte-identical to their originals
- `/app/hexanalysis/{name}.hexdump` — annotated hex dump of each original corpus file with record-boundary comment lines at logical record start offsets (see spec Section 8 for exact format)
- `/app/integrity.sig` — keyed HMAC-SHA256 digest of each reconstructed file using `/app/hmac.key`; one line per file sorted by filename: `{64-hex-chars}  {filename}`
- `/app/checksums.txt` — SHA-256 hash of each reconstructed file; one line per file sorted by filename: `{64-hex-chars}  {filename}`

The toolkit must expose importable functions `analyze_file(filepath)` returning the sorted violation list and `reconstruct_file(filepath, outpath)` writing the repaired transaction.