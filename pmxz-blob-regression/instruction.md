The HPC job scheduler's process-map serialization library at `/app/` has multiple failures across its modules. Your job is to diagnose the root causes, fix all bugs, implement the v3 format, and build a migration tool.

## Observed failures

1. **Large-job round-trip corruption**: Serializing and immediately deserializing a process map with ~1000+ processes throws a decompression error or returns corrupt data. Small process maps (under ~500 processes) serialize and deserialize correctly.

2. **Incorrect format metadata**: `get_format_info()` in `/app/procmap/serialize.py` returns wrong values for `version`, `header_size`, and `uncompressed_size` on certain blob inputs.

3. **Valid data rejected**: `validate_serialized_data()` in `/app/procmap/validate.py` rejects blobs that should be accepted, and reports incorrect metadata for some inputs.

Investigate the codebase — including `/app/procmap/serialize.py`, `/app/procmap/validate.py`, `/app/procmap/compress.py`, `/app/config.py`, and any documentation files in `/app/` — to understand the format history and diagnose what's going wrong.

## Required outcomes

When you are done, all of the following must hold:

- All existing PMXZ format versions round-trip correctly through `deserialize_procmap()` with proper format auto-detection
- `get_format_info()` correctly reports `version`, `header_size`, `uncompressed_size`, and `compression_ratio` for all supported blob formats and raw data
- `validate_serialized_data()` accepts all valid formats and returns correct per-version metadata (`version`, `payload_size`)
- `serialize_procmap_v3(procmap_str, algorithm)` exists in `/app/procmap/serialize.py`, implementing the format specified in `/app/REQUIREMENTS_V3.md`; supported algorithms: `'zlib'`, `'lzma'`, `'zstd'`; zstd-compressed payloads must be independently decompressable by the `zstd` CLI tool
- v3 deserialization verifies CRC32 integrity and raises `ValueError` (message containing `"CRC32"`) on checksum mismatch
- `/app/migrate.py` accepts a directory path argument, converts every `.pmx` file to v3 in-place, and writes `<dir>/migration_report.json` containing: `total_files` (int), `migrated` (int), `errors` (int), `by_source_format` (format name to count dict), `error_files` (list of filenames that failed); corrupted files are reported gracefully without crashing
- `/app/migrate.py` also writes `<dir>/migration_checksums.sha256` — a `sha256sum --check` compatible manifest of all successfully migrated files