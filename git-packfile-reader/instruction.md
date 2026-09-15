A minimal Git object library exists at `/app/gitlib.py`. It defines `GitRepository`, `GitBlob`, `GitCommit`, `GitTree`, `GitTag`, and functions `object_read(repo, sha)` and `object_hash(data, fmt)`. A Git repository is at `/app/repo/`.

Currently, calling `gitlib.object_read(repo, sha)` raises an exception for every object in the repository because `git gc` was run, which reorganized the repository's internal object storage. Investigate the repository structure to determine why the library fails and extend it so that all objects can be read.

**Task 1 — Fix the library**: Extend `/app/gitlib.py` (and/or add supporting modules in `/app/`) so that `object_read` successfully returns the correct `GitObject` subclass for every reachable object. The returned object's `serialize()` output must match `git cat-file -p <sha>` byte-for-byte, and `obj.fmt` must match `git cat-file -t <sha>`.

**Task 2 — Build a CLI object viewer**: Create an executable Python script at `/app/wyag-cat-file` that reads Git objects using the library. Required interface:

- `/app/wyag-cat-file -t <sha>` — prints the object type name (e.g. `commit`) followed by a newline
- `/app/wyag-cat-file -p <sha>` — prints the object content, byte-for-byte identical to `git cat-file -p` output (including correct pretty-printing of tree objects with zero-padded modes and resolved entry types)
- `--repo <path>` — optional flag to specify repository path (default: `/app/repo`)

The script must have a proper Python shebang and be executable via `chmod +x`.