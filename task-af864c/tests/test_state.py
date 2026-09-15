#!/usr/bin/env python3
"""Tests for the ext2 filesystem image builder task."""


import os
import re
import struct
import subprocess
import tempfile


IMAGE_PATH = "/app/ext2.img"


def _debugfs_dump(fs_path, local_path):
    """Dump a file from the ext2 image to a local path using debugfs."""
    result = subprocess.run(
        ["debugfs", "-R", f"dump {fs_path} {local_path}", IMAGE_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"debugfs dump {fs_path} failed: {result.stderr}"


def _debugfs_ls(dir_path):
    """List a directory inside the ext2 image."""
    result = subprocess.run(
        ["debugfs", "-R", f"ls {dir_path}", IMAGE_PATH],
        capture_output=True, text=True,
    )
    return result.stdout


def _debugfs_stat(path):
    """Stat a path inside the ext2 image."""
    result = subprocess.run(
        ["debugfs", "-R", f"stat {path}", IMAGE_PATH],
        capture_output=True, text=True,
    )
    return result.stdout


def _dump_and_read(fs_path):
    """Dump a file from the image and return its bytes."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        path = tmp.name
    try:
        _debugfs_dump(fs_path, path)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


# ========== Structural tests ==========

def test_image_exists_and_size():
    assert os.path.exists(IMAGE_PATH), "Image file /app/ext2.img does not exist"
    size = os.path.getsize(IMAGE_PATH)
    assert size == 4194304, f"Image size is {size}, expected 4194304 (4 MiB)"


def test_superblock_magic():
    with open(IMAGE_PATH, "rb") as f:
        f.seek(1024 + 56)
        magic = struct.unpack("<H", f.read(2))[0]
    assert magic == 0xEF53, f"Superblock magic is 0x{magic:04X}, expected 0xEF53"


def test_block_size():
    with open(IMAGE_PATH, "rb") as f:
        f.seek(1024 + 24)
        log_bs = struct.unpack("<I", f.read(4))[0]
    bs = 1024 << log_bs
    assert bs == 1024, f"Block size is {bs}, expected 1024"


def test_revision_level():
    with open(IMAGE_PATH, "rb") as f:
        f.seek(1024 + 76)
        rev = struct.unpack("<I", f.read(4))[0]
    assert rev >= 1, f"Revision level is {rev}, expected >= 1 (dynamic revision)"


def test_filetype_feature():
    with open(IMAGE_PATH, "rb") as f:
        f.seek(1024 + 96)
        incompat = struct.unpack("<I", f.read(4))[0]
    assert incompat & 0x0002, (
        f"EXT2_FEATURE_INCOMPAT_FILETYPE (0x0002) not set; "
        f"s_feature_incompat = 0x{incompat:08X}"
    )


def test_volume_name():
    result = subprocess.run(
        ["dumpe2fs", "-h", IMAGE_PATH],
        capture_output=True, text=True,
    )
    match = re.search(r"Filesystem volume name:\s+(\S+)", result.stdout)
    assert match, "Could not find volume name in dumpe2fs output"
    assert match.group(1) == "tbench-ext2", (
        f"Volume name is '{match.group(1)}', expected 'tbench-ext2'"
    )


def test_fsck_passes():
    result = subprocess.run(
        ["fsck.ext2", "-fn", IMAGE_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"fsck.ext2 -fn exited with code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ========== Directory structure tests ==========

def test_root_directory_listing():
    out = _debugfs_ls("/")
    for name in ("lost+found", "README", "data", "config", "logs"):
        assert name in out, f"'{name}' not found in root directory listing"


def test_data_directory_listing():
    out = _debugfs_ls("/data")
    for name in ("measurements.csv", "large.bin"):
        assert name in out, f"'{name}' not found in /data listing"


def test_config_directory_listing():
    out = _debugfs_ls("/config")
    for name in ("settings.conf", "settings.bak"):
        assert name in out, f"'{name}' not found in /config listing"


def test_logs_directory_listing():
    out = _debugfs_ls("/logs")
    assert "access.log" in out, "'access.log' not found in /logs listing"


# ========== File content tests ==========

def test_readme_content():
    got = _dump_and_read("/README")
    expected = b"ext2 filesystem created from scratch for this task.\n"
    assert got == expected, (
        f"README content mismatch.\n"
        f"Expected ({len(expected)} bytes): {expected!r}\n"
        f"Got      ({len(got)} bytes): {got!r}"
    )


def test_measurements_csv():
    got = _dump_and_read("/data/measurements.csv")
    content = got.decode()
    lines = content.strip().split("\n")
    assert lines[0] == "id,value,square", f"CSV header mismatch: {lines[0]!r}"
    assert len(lines) == 11, f"Expected 11 lines (header + 10 rows), got {len(lines)}"
    for i, line in enumerate(lines[1:], 1):
        parts = line.split(",")
        assert len(parts) == 3, f"Row {i}: expected 3 columns, got {len(parts)}"
        assert int(parts[0]) == i, f"Row {i}: id column is {parts[0]}, expected {i}"
        assert int(parts[1]) == i, f"Row {i}: value column is {parts[1]}, expected {i}"
        assert int(parts[2]) == i * i, f"Row {i}: square column is {parts[2]}, expected {i*i}"


def test_large_bin_content():
    got = _dump_and_read("/data/large.bin")
    assert len(got) == 14336, f"large.bin is {len(got)} bytes, expected 14336"
    expected = bytes([i % 251 for i in range(14336)])
    assert got == expected, "large.bin content does not match pattern byte[i] = i % 251"


def test_settings_conf_content():
    got = _dump_and_read("/config/settings.conf")
    expected = b"key=value\ndebug=false\ntimeout=30\n"
    assert got == expected, (
        f"settings.conf content mismatch.\n"
        f"Expected: {expected!r}\nGot: {got!r}"
    )


def test_settings_bak_content():
    """settings.bak must have identical content to settings.conf (hard link)."""
    got = _dump_and_read("/config/settings.bak")
    expected = b"key=value\ndebug=false\ntimeout=30\n"
    assert got == expected, (
        f"settings.bak content mismatch.\n"
        f"Expected: {expected!r}\nGot: {got!r}"
    )


def test_access_log_content():
    got = _dump_and_read("/logs/access.log")
    expected = b"2024-01-01 00:00:00 GET /index.html 200\n"
    assert got == expected, (
        f"access.log content mismatch.\n"
        f"Expected: {expected!r}\nGot: {got!r}"
    )


# ========== Hard link tests ==========

def test_hard_link_same_inode():
    """settings.conf and settings.bak must be hard links (same inode number)."""
    stat1 = _debugfs_stat("/config/settings.conf")
    stat2 = _debugfs_stat("/config/settings.bak")
    ino1 = re.search(r"Inode:\s+(\d+)", stat1)
    ino2 = re.search(r"Inode:\s+(\d+)", stat2)
    assert ino1 and ino2, "Could not extract inode numbers from debugfs stat"
    assert ino1.group(1) == ino2.group(1), (
        f"settings.conf (inode {ino1.group(1)}) and settings.bak (inode {ino2.group(1)}) "
        f"are not hard links — they must share the same inode"
    )


def test_hard_link_count():
    """The shared inode for settings.conf/settings.bak must have link count 2."""
    stat = _debugfs_stat("/config/settings.conf")
    links = re.search(r"Links:\s+(\d+)", stat)
    assert links, "Could not extract link count from debugfs stat"
    assert int(links.group(1)) == 2, (
        f"Hard-linked file link count is {links.group(1)}, expected 2"
    )


# ========== Indirect block test ==========

def test_large_bin_uses_indirect_blocks():
    """large.bin inode must have a non-zero singly indirect block pointer."""
    stat = _debugfs_stat("/data/large.bin")
    ino_match = re.search(r"Inode:\s+(\d+)", stat)
    assert ino_match, "Could not extract large.bin inode number"
    ino = int(ino_match.group(1))

    with open(IMAGE_PATH, "rb") as f:
        # Read superblock fields
        f.seek(1024 + 24)
        log_bs = struct.unpack("<I", f.read(4))[0]
        bs = 1024 << log_bs

        f.seek(1024 + 88)
        inode_size = struct.unpack("<H", f.read(2))[0]

        # BGDT is at the block after the superblock
        bgd_off = bs * 2 if bs == 1024 else bs
        f.seek(bgd_off + 8)
        itbl_block = struct.unpack("<I", f.read(4))[0]

        # Read singly indirect pointer from inode (offset 88 in inode struct)
        ino_off = itbl_block * bs + (ino - 1) * inode_size
        f.seek(ino_off + 4)
        fsize = struct.unpack("<I", f.read(4))[0]
        assert fsize == 14336, f"large.bin inode size is {fsize}, expected 14336"

        f.seek(ino_off + 88)
        indirect_ptr = struct.unpack("<I", f.read(4))[0]

    assert indirect_ptr != 0, (
        "large.bin inode singly-indirect block pointer is 0 — "
        "the file must use indirect blocks for 14 KiB with 1024-byte blocks"
    )


# ========== Permission tests ==========

def test_directory_permissions():
    """Verify directory permissions match the specification."""
    checks = [
        ("/",           0o0755),
        ("/lost+found", 0o0700),
        ("/data",       0o0755),
        ("/config",     0o0755),
        ("/logs",       0o0755),
    ]
    for path, expected_perms in checks:
        stat = _debugfs_stat(path)
        mode_match = re.search(r"Mode:\s+(\d+)", stat)
        assert mode_match, f"Could not extract mode for {path} from: {stat[:200]}"
        mode = int(mode_match.group(1), 8)
        perms = mode & 0o7777
        assert perms == expected_perms, (
            f"Directory {path} permissions are {oct(perms)}, expected {oct(expected_perms)}"
        )


def test_file_permissions():
    """Verify regular file permissions are 0644."""
    files = ["/README", "/data/measurements.csv", "/data/large.bin",
             "/config/settings.conf", "/logs/access.log"]
    for path in files:
        stat = _debugfs_stat(path)
        mode_match = re.search(r"Mode:\s+(\d+)", stat)
        assert mode_match, f"Could not extract mode for {path} from: {stat[:200]}"
        mode = int(mode_match.group(1), 8)
        perms = mode & 0o7777
        assert perms == 0o0644, (
            f"File {path} permissions are {oct(perms)}, expected {oct(0o0644)}"
        )


# ========== Anti-cheat ==========

def test_no_forbidden_tools():
    """Builder and solution must not reference filesystem creation tools."""
    forbidden = ["mke2fs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "genext2fs", "fuse2fs"]
    for scan_dir in ["/solution", "/app"]:
        for dirpath, _dirs, files in os.walk(scan_dir):
            for fname in files:
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", errors="ignore") as fh:
                        text = fh.read()
                    for cmd in forbidden:
                        assert cmd not in text, (
                            f"File {fpath} references forbidden tool '{cmd}'"
                        )
                except IOError:
                    pass
