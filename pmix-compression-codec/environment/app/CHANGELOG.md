# PPN Codec Changelog

## v2.2.0 (2026-06-01) — planned

### New features
- Codec specification for TAG_PACKED (0x03) binary format
  (`SPEC.md`). Supports CONTIGUOUS, STRIDED, and EXPLICIT per-node
  encoding for compact representation of structured HPC topologies.
- Format auto-selection: `ppn_encode()` must choose the smallest
  encoding among TAG_RAW, TAG_BLOB, and TAG_PACKED.

### Known issues
- TAG_BLOB decode path regressed in v2.1.0 (compressed round-trips
  produce incorrect results for large process counts).
- TAG_PACKED encoder and decoder are not yet implemented.

## v2.1.0 (2026-05-15)

### Optimizations
- Compression module: replaced conservative `deflateBound`-based pre-check
  with post-compression actual size comparison. Inputs near the 4 KiB
  threshold that previously fell back to raw format can now benefit from
  compression when zlib achieves a favorable ratio.

### Refactoring
- Decode pipeline: unified format dispatch through single entry point to
  reduce code duplication across decode paths.

## v2.0.3 (2026-03-01)

### Bug fixes
- Fixed memory leak in rank-list serializer for empty node groups.
- Corrected off-by-one in node-count calculation when trailing semicolon
  is present.

## v2.0.0 (2025-11-01)

### Initial release
- Raw and compressed PPN map encoding/decoding.
- zlib-based compression for maps exceeding 4096 bytes.
- Contiguous rank allocation across nodes.
- Round-trip verification test driver (`ppn_test`).
