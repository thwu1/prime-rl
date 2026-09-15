A researcher's formal power series computation project at `/app/workspace/` stalled after multiple failures. The workspace contains:

- A SQLite project database (`project.db`) with a computation journal
- Binary polynomial data files in a custom format under `data/`
- Algorithm notes under `notes/` and run logs under `logs/`
- A compiled polynomial arithmetic tool at `/app/bin/polytool`

The journal records the full computation history: steps that succeeded, integrity checks that failed, and runs that crashed. At least one intermediate data file on disk is corrupted — the journal documents the verification failure but the corruption was never resolved. A previous computation attempt that ignored this corruption was killed by the OS before completing.

Analyze the workspace to determine what computation is being performed. Diagnose which intermediate results can be trusted by understanding and verifying the mathematical relationships they must satisfy. Identify the last known-good checkpoint, evaluate the algorithmic approaches described in the notes, and complete the remaining computation. The target operation requires handling 65536 polynomial coefficients over Z/998244353Z — naive O(N²) polynomial multiplication will not scale; an NTT-based O(N log N) implementation is necessary.

Write the final 65536-coefficient result to `/app/workspace/output/g_final.poly` using the project's binary polynomial format: 4-byte ASCII magic `POLY`, followed by the prime as a little-endian uint32, the coefficient count as a little-endian uint32, then all coefficients as consecutive little-endian uint32 values.