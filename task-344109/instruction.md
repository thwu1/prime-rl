A compound evidence container at `/app/evidence.bin` was produced during a file carving operation on a seized storage device. It contains multiple ZIP archives embedded at unknown byte offsets, interspersed with unstructured binary padding. The container begins with a 32-byte header (`EVDNC_CONTAINER_V1\0`, zero-padded).

A case metadata database at `/app/casedb.sqlite` (SQLite3 format) contains a `case_info` table with case context, and a `specimens` table mapping SHA-256 hashes to specimen identifiers and case references.

The environment provides `binwalk`, `yara`, `ssdeep`, `sqlite3`, `xxd`, and `file`. The following artifacts must all exist when the task is complete:

**`/app/binwalk_scan.json`** — Structured JSON report of all signatures detected by `binwalk` in the evidence container:

```json
{
  "signatures": [
    {"offset": "<int: byte offset>", "description": "<binwalk description string>"}
  ],
  "total_signatures": "<int>"
}
```

**`/app/extracted/`** — Each ZIP archive recovered from the evidence container, named `specimen_1.zip` through `specimen_N.zip` in order of their byte offset within the container. The SHA-256 hash of each extracted file must match the corresponding entry in the `specimens` database table.

**`/app/classify.yar`** — YARA rules file containing at least one rule per structural variation observed in the recovered specimens: zip64 extended format, prepended non-ZIP data, non-ASCII filename encodings, and ambiguous end-of-archive markers. Each rule must include `meta:` fields for `author`, `description`, and `severity`.

**`/app/yara_results.json`** — JSON mapping each specimen filename to the list of YARA rule names that matched when scanning with `/app/classify.yar`:

```json
{
  "specimen_1.zip": [],
  "specimen_2.zip": ["matched_rule_name"]
}
```

**`/app/integrity.sha256`** — SHA-256 checksums for every extracted archive, one per line, in standard `sha256sum` output format (hash, two spaces, filename).

**`/app/integrity.ssdeep`** — Fuzzy hashes for every extracted archive in ssdeep's standard output format.

**`/app/zipforensics.py`** — A raw binary ZIP parser accepting a single file path argument and printing JSON to stdout. It must not import or use Python's `zipfile`, `zipimport`, or any third-party ZIP parsing library. Output schema:

```json
{
  "eocd_offset": "<int: byte position of the End of Central Directory record>",
  "total_entries": "<int>",
  "central_directory_offset": "<int: actual byte position of the central directory>",
  "is_zip64": "<bool>",
  "prepended_data_size": "<int: bytes before the first local file header>",
  "entries": [
    {
      "filename": "<string: decoded filename>",
      "filename_encoding": "<utf-8|shift_jis|cp437>",
      "compressed_size": "<int>",
      "uncompressed_size": "<int>",
      "compression_method": "<int>",
      "mod_datetime": "<YYYY-MM-DDTHH:MM:SS>",
      "crc32": "<8-char lowercase hex>",
      "local_header_offset": "<int: actual byte position in the file>"
    }
  ]
}
```

**`/app/report.json`** — Consolidated forensic report merging extraction context, database records, tool outputs, and parser analysis:

```json
{
  "case_id": "<from case_info table>",
  "analyst": "<from case_info table>",
  "specimens": [
    {
      "specimen_id": "<int: from specimens table>",
      "sha256": "<hex>",
      "ssdeep": "<fuzzy hash string>",
      "case_ref": "<from specimens table>",
      "extraction_offset": "<int: byte position within evidence.bin>",
      "extraction_size": "<int: byte length of the archive>",
      "yara_matches": ["<rule_name>", "..."],
      "analysis": { "...zipforensics.py output for this specimen..." }
    }
  ]
}
```

The `analysis` object for each specimen is the full output of `zipforensics.py` run on that specimen. The embedded archives contain non-trivial structural variations — the parser must handle whatever it encounters.