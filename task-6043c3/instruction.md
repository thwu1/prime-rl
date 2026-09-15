A Git repository at `/app/repo/` has suffered dual corruption: the pack index file (`.idx`) under `.git/objects/pack/` has been deleted, and the pack file's trailing 20-byte SHA-1 integrity checksum has been overwritten with null bytes. As a result, `git index-pack`, `git log`, `git fsck`, and all other standard git commands fail. The repository is unusable.

Restore the repository to full working order and produce the following deliverables:

**Repaired pack file**: The `.pack` file's trailing SHA-1 checksum must be corrected in-place. The pack checksum is the SHA-1 digest computed over all bytes in the file that precede the final 20-byte checksum field. You will need to inspect the raw binary pack data, compute the correct checksum, and patch the file.

**Pack parser** at `/app/packparse.py`: A self-contained Python program that reads objects from the raw pack file by SHA-1 hash and regenerates a valid pack index — without invoking external commands (`subprocess`, `os.system`, `os.popen`) or using any git library (`pygit2`, `dulwich`, `gitpython`).

```
python3 /app/packparse.py /app/repo/.git -t <sha1>         # print resolved type
python3 /app/packparse.py /app/repo/.git -p <sha1>         # print object content
python3 /app/packparse.py /app/repo/.git --rebuild-index    # regenerate .idx
```

`-t` and `-p` output must be byte-identical to `git cat-file`. Exit non-zero for objects not found in the pack.

**Rebuilt pack index**: After running `--rebuild-index`, the generated `.idx` must pass `git verify-pack -v`, and all standard git operations (`git log`, `git fsck --no-dangling`) must succeed.

**Recovery bundle** at `/app/recovered.bundle`: A portable git bundle containing all branches, verifiable with `git bundle verify`.

**Verification report** at `/app/verify_report.txt`: The complete output of running `git verify-pack -v` on the rebuilt pack index.

The repository contains multiple branches, merge commits, nested directory trees, delta-compressed objects, and files revised across several commits. All objects must be recoverable regardless of how they are stored or compressed within the pack.