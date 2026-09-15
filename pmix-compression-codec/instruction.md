The `/app/` directory contains a PPN (Process-Per-Node) map codec for an HPC job launcher. It encodes and decodes rank placement maps that describe which MPI ranks are assigned to which compute nodes.

After the v2.1.0 refactor (see `/app/CHANGELOG.md`), the TAG_BLOB compressed decoder regressed — large process counts that trigger zlib compression decode to incorrect maps.

The file `/app/SPEC.md` specifies a new TAG_PACKED (0x03) binary format designed for compact encoding of structured rank assignments (contiguous, strided, and explicit per-node encoding types). This format is not yet implemented.

Deliver a working codec that:

- Correctly round-trips maps through all three formats (TAG_RAW, TAG_BLOB, TAG_PACKED)
- Implements TAG_PACKED encoder and decoder per `/app/SPEC.md`, including CONTIGUOUS, STRIDED, and EXPLICIT encoding types with correct per-node type selection
- Auto-selects the smallest format in `ppn_encode()` by comparing encoded sizes across all three formats (tie-breaking: TAG_PACKED > TAG_BLOB > TAG_RAW)
- Handles strided and irregular (non-contiguous) rank assignments, not just contiguous sequences
- Builds cleanly with `make -C /app clean all`

Run `/app/ppn_test` to verify — all tests must report 0 failures.