# Changelog

## v3.0.0 (planned)

### Requirements
- New PMXZ v3 format with CRC32 integrity checking, multi-algorithm compression
  support (zlib + lzma + zstd), and explicit compressed-length field.
  See REQUIREMENTS_V3.md for full specification.
- Migration tool for converting legacy .pmx files (raw, v1, v2) to v3 format.
- Backward-compatible deserialization: must handle raw, v1, v2, and v3 formats.
- SHA-256 checksum manifest for post-migration verification.

## v2.1.0 (2025-10-15)

### Improvements
- Compression: Removed overly conservative deflateBound pre-check that was
  rejecting data that could compress well. Now uses actual compressed output
  for size decisions. This improves compression utilization for process maps
  near the threshold boundary.
- Serialization: Added format version byte to PMXZ blob header for forward
  compatibility with future format changes (PMXZ v2 format).
- Compression: Updated default compression level from 1 to 6 for better
  compression ratios on large process maps.

### Bug Fixes
- Fixed edge case in generator where nnodes > nprocs would produce
  empty node entries (now raises ValueError).

## v2.0.0 (2025-06-01)

### Major Changes
- Introduced PMXZ blob format for compressed process maps.
- Added process map validation module.
- Added compression statistics tracking.
- Switched from pickle-based to custom binary format for storage.

### New Features
- ProcessRegistry class for managing job process maps.
- Batch serialization/deserialization support.
- Local file cache for frequently accessed process maps.

## v1.0.0 (2025-01-15)

### Initial Release
- Process map generator for multi-node HPC jobs.
- Raw text serialization format.
- Basic process map parsing and validation.
