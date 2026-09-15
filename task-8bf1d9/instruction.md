The git repository at `/app/repo/` is non-functional. Multiple independent issues prevent normal git operations.

The most critical problem: the pack index (`.idx`) file is missing and `git index-pack` has been removed from the system — it will not work. Write a Python program at `/app/pack_index_gen.py` that reads a Git Pack v2 format `.pack` file (passed as its sole command-line argument) and generates the corresponding Pack Index v2 (`.idx`) file in the same directory. Your implementation must correctly parse all pack entry types — including variable-length object headers, OFS_DELTA and REF_DELTA delta-compressed objects — resolve delta chains to recover base types and compute per-object SHA-1 identities, compute per-entry CRC32 checksums over the raw pack bytes, build the 256-entry fanout table, and emit valid trailing checksums for both the pack and the index itself. The generated index must be fully interoperable with standard git tooling.

The repository has additional configuration and reference issues that must be independently diagnosed and repaired.

**Success criteria:**
- `/app/pack_index_gen.py` exists and generates correct `.idx` files from arbitrary `.pack` files (it will be tested against a pack file you have not seen)
- `git -C /app/repo fsck --full --strict` exits 0 with no errors
- `git -C /app/repo log --oneline` shows the complete commit history (5 commits)
- All committed files are recoverable via `git -C /app/repo show HEAD:<path>`
- `git -C /app/repo verify-pack -v` succeeds on all pack files
- All tags are accessible and valid