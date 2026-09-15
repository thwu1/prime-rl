Write a program that constructs a valid ext2 filesystem image at `/app/ext2.img` by writing every on-disk structure from raw bytes — superblock, block group descriptor table, block and inode bitmaps, inode table, directory entries, file data blocks, and a singly indirect block. Use only the Python standard library (no external packages).

## Image Parameters

- **Size**: exactly 4,194,304 bytes (4 MiB)
- **Block size**: 1024 bytes
- **Revision**: 1 (`EXT2_DYNAMIC_REV`) with `s_first_ino = 11`, `s_inode_size = 128`
- **Required incompatible feature**: `EXT2_FEATURE_INCOMPAT_FILETYPE` (0x0002)
- **Volume name**: `tbench-ext2`

## Required Directory Tree and File Contents

```
/
├── lost+found/           (directory, mode 0700)
├── README                (regular file, mode 0644)
│     content: "ext2 filesystem created from scratch for this task.\n"
├── data/                 (directory, mode 0755)
│   ├── measurements.csv  (regular file, mode 0644)
│   │     content: CSV with header "id,value,square" and 10 rows: i,i,i² for i=1..10
│   │              each row newline-terminated, file ends with newline
│   └── large.bin         (regular file, mode 0644, exactly 14336 bytes)
│         content: byte[i] = i % 251 for i in 0..14335
├── config/               (directory, mode 0755)
│   ├── settings.conf     (regular file, mode 0644)
│   │     content: "key=value\ndebug=false\ntimeout=30\n"
│   └── settings.bak      hard link to settings.conf (same inode, link count = 2)
└── logs/                 (directory, mode 0755)
    └── access.log        (regular file, mode 0644)
          content: "2024-01-01 00:00:00 GET /index.html 200\n"
```

All directories have mode 0755 except `lost+found` which has mode 0700.

## Constraints

- `fsck.ext2 -fn /app/ext2.img` must exit with code 0
- `settings.conf` and `settings.bak` must be hard links sharing one inode
- `large.bin` must use a singly indirect block pointer (14 × 1024-byte blocks exceed 12 direct pointer slots)
- Filesystem creation tools (`mke2fs`, `mkfs.ext2`, `mkfs.ext3`, `mkfs.ext4`, `genext2fs`, `fuse2fs`) have been removed from the system — do not attempt to use them
- You may use `fsck.ext2`, `debugfs`, and `dumpe2fs` for inspection and debugging