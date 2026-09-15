A 64MB FAT32 filesystem image at `/app/disk.img` has sustained multi-layer metadata corruption. The filesystem uses a nested directory structure with six files distributed across root, `docs/`, and `logs/` subdirectories. All file data clusters are intact — only metadata is damaged.

Produce a fully repaired image at `/app/repaired.img` that satisfies all of the following:

- `fsck.vfat -n` reports zero errors
- Both FAT table copies are identical and structurally correct
- No orphaned cluster chains remain (all allocated clusters must be reachable from the directory tree)
- All six files are extractable via `mtools` with byte-exact original content
- FSInfo free cluster count and next-free-cluster are accurate
- Backup boot sector is consistent with the primary boot sector
- The data region is byte-identical to the original

The corruption is non-trivial: both FAT copies have been independently damaged at different locations — some entries zeroed, some overwritten with incorrect non-zero values. For the zeroed entries, the other FAT copy retains the correct value. For the non-zero conflicting entries, neither FAT can be blindly trusted; the correct entry must be determined through structural analysis. Additionally, orphaned cluster chains exist that are allocated in both FATs but not referenced by any directory entry in the filesystem tree.

Tools available in the environment: `dosfstools` (`fsck.vfat`, `mkfs.vfat`), `mtools` (`mdir`, `mcopy`, `minfo`, `mtype`, `mshowfat`), `xxd`, `hexdump`, Python 3.