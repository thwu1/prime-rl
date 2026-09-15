A plausibly deniable encrypted key-value store is implemented at `/app/pddb.py`. It manages a flat binary disk image (256 pages x 4096 bytes) with encrypted multi-basis overlays. When a Basis is locked, its pages are cryptographically indistinguishable from free space, providing plausible deniability.

The current implementation has two gaps:

1. **Free-space side channel**: Every page allocation scans the entire disk, which lets an observer determine the total amount of free space — a deniability leak. The system needs a bounded free-page cache that limits how much free-space information is disclosed at any point. The cache must persist in encrypted form on disk across close/reopen cycles and integrate with the existing basis page-table infrastructure.

2. **No portable export/import**: There is no way to export a basis's entries to a portable file that can be imported into a different PDDB instance, nor any mechanism for independent integrity verification of exported data using standard command-line tools without Python cryptographic libraries.

Extend `/app/pddb.py` to close both gaps. Additionally, write a verification shell script at `/app/verify_export.sh` that can verify the integrity of an exported file using `openssl` for all cryptographic operations (Python may only be used for JSON parsing).

The test suite at `/tests/test_state.py` defines the exact API contracts, constructor parameters, method signatures, data formats, cryptographic protocols, and behavioral expectations for both subsystems. Read the tests carefully and satisfy all of them.