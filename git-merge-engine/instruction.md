A git repository's complete object store has been exported to a custom JSON-based archive at `/app/archive/`. The original repository no longer exists. Reconstruct a fully working git repository at `/app/repo/` from the archived data.

The archive contains structured representations of every git object (blobs, trees, commits, tags) along with reference and metadata files. Examine the archive contents to understand the export format.

Objects in the archive are stored as structured JSON — not in git's native binary format. You must re-encode each object into the format git expects internally, paying close attention to how git represents different object types at the byte level.

When complete:

- `git fsck --strict --no-dangling` must exit cleanly with no errors
- All original branches and tags must be intact and resolvable
- `git log --all --oneline` must show the complete commit history across all branches
- Checking out any branch must produce a clean working tree with the correct source files

Note: Some reference data in the archive is incomplete — one branch ref was lost during export. Use the commit graph and the provided metadata to reconstruct it.