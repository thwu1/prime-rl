A corrupted xv6 file system disk image is at `/app/fs.img`. The image was captured after a system crash and contains multiple consistency violations.

Format reference materials are in `/app/xv6-src/`:
- `fs.h` — on-disk data structure definitions (superblock, dinode, dirent, layout constants)
- `mkfs.c` — standalone filesystem image builder (compile: `gcc -Wall -o mkfs mkfs.c`)
- `log.c`, `fs.c` — xv6 kernel source showing the write-ahead log protocol and filesystem operations (reference only, not standalone-compilable)

Binary analysis tools (`xxd`, `gcc`, `cmp`, `dd`) are installed.

Analyze the corrupted image, identify all consistency violations, repair them, and produce:

**`/app/fs_repaired.img`** — the fully consistent repaired image with all valid data preserved.

**`/app/fsck_report.json`** — a JSON diagnostic report:

```json
{
  "log_entries_replayed": <int>,
  "orphaned_inodes": [<sorted inode numbers>],
  "bitmap_errors": {
    "marked_used_but_free": [<sorted block numbers>],
    "marked_free_but_used": [<sorted block numbers>]
  },
  "size_errors": [{"inum": <int>, "reported_size": <int>, "correct_size": <int>}],
  "recovered_files": {"<filename>": "<file content as string>"}
}
```

Bitmap error lists must reflect the state after orphan cleanup is complete. The repaired image log header must be cleared.