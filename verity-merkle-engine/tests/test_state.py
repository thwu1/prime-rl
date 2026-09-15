"""Tests for dm-verity forensic analysis tool.

Validates that /app/verity_forensics.py correctly parses on-disk superblocks,
independently verifies Merkle hash tree integrity, detects data corruption,
and generates valid device-mapper target table strings.
"""

import json
import os
import struct
import subprocess

import pytest

TOOL = "/app/verity_forensics.py"
SALT_A = "aa" * 32  # 32-byte salt (all 0xaa)
SALT_B = "0123456789abcdef" * 4  # 32-byte salt


def create_data_image(path, size_mb):
    """Create a deterministic data file with unique content per 4096-byte block."""
    nblocks = size_mb * 1024 * 1024 // 4096
    with open(path, "wb") as f:
        for i in range(nblocks):
            idx = struct.pack("<Q", i)
            f.write((idx * 512)[:4096])


def veritysetup_format(data, hash_file, salt, algorithm="sha256",
                       data_block_size=4096, hash_block_size=4096,
                       hash_offset=None):
    """Run veritysetup format (with superblock) and return parsed output."""
    cmd = [
        "veritysetup", "format",
        f"--salt={salt}",
        f"--hash={algorithm}",
        f"--data-block-size={data_block_size}",
        f"--hash-block-size={hash_block_size}",
    ]
    if hash_offset is not None:
        cmd.append(f"--hash-offset={hash_offset}")
    cmd.extend([data, hash_file])
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return _parse_vs_output(r.stdout)


def _parse_vs_output(text):
    """Parse veritysetup format/dump output into a dict."""
    info = {}
    mapping = {
        "UUID": ("uuid", str),
        "Hash type": ("hash_type", int),
        "Data blocks": ("data_blocks", int),
        "Data block size": ("data_block_size", int),
        "Hash block size": ("hash_block_size", int),
        "Hash algorithm": ("algorithm", str),
        "Salt": ("salt", lambda x: x.strip().lower()),
        "Root hash": ("root_hash", lambda x: x.strip().lower()),
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key in mapping:
            name, conv = mapping[key]
            info[name] = conv(val)
    return info


def run_tool(subcommand, **kwargs):
    """Run /app/verity_forensics.py with given subcommand and keyword arguments."""
    cmd = ["python3", TOOL, subcommand]
    for k, v in kwargs.items():
        cmd.extend(["--" + k.replace("_", "-"), str(v)])
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Superblock parse tests
# ---------------------------------------------------------------------------
class TestParse:

    def test_parse_sha256(self, tmp_path):
        """Parse superblock from a sha256-formatted hash image."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A)

        r = run_tool("parse", hash=himg)
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        p = json.loads(r.stdout)

        assert p["version"] == 1
        assert p["hash_type"] == ref["hash_type"]
        assert p["uuid"] == ref["uuid"]
        assert p["algorithm"] == "sha256"
        assert p["data_block_size"] == 4096
        assert p["hash_block_size"] == 4096
        assert p["data_blocks"] == ref["data_blocks"]
        assert p["salt"] == SALT_A
        assert p["salt_size"] == 32

    def test_parse_sha512(self, tmp_path):
        """Parse superblock with sha512 algorithm."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A, algorithm="sha512")

        r = run_tool("parse", hash=himg)
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        p = json.loads(r.stdout)
        assert p["algorithm"] == "sha512"
        assert p["data_blocks"] == ref["data_blocks"]
        assert p["uuid"] == ref["uuid"]

    def test_parse_invalid_superblock(self, tmp_path):
        """Random data should be rejected as invalid superblock."""
        bad = str(tmp_path / "bad.img")
        with open(bad, "wb") as f:
            f.write(os.urandom(512))

        r = run_tool("parse", hash=bad)
        assert r.returncode == 1
        assert "INVALID_SUPERBLOCK" in r.stderr

    def test_parse_at_hash_offset(self, tmp_path):
        """Parse superblock from a combined image at a non-zero offset."""
        data = str(tmp_path / "combined.img")
        create_data_image(data, 4)
        offset = 4 * 1024 * 1024
        ref = veritysetup_format(data, data, SALT_A, hash_offset=offset)

        r = run_tool("parse", hash=data, hash_offset=offset)
        assert r.returncode == 0, f"parse at offset failed: {r.stderr}"
        p = json.loads(r.stdout)
        assert p["data_blocks"] == ref["data_blocks"]
        assert p["uuid"] == ref["uuid"]
        assert p["salt"] == SALT_A


# ---------------------------------------------------------------------------
# Integrity audit tests
# ---------------------------------------------------------------------------
class TestAudit:

    def test_clean_image(self, tmp_path):
        """Audit of an unmodified image reports no corruption."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A)

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0, f"audit failed: {r.stderr}"
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is True
        assert rpt["corrupted_blocks"] == []
        assert rpt["root_hash"] == ref["root_hash"]
        assert rpt["data_blocks"] == ref["data_blocks"]
        assert rpt["corruption_pct"] == 0.0

    def test_single_block_corruption(self, tmp_path):
        """Corrupting one data block is detected and localized."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        veritysetup_format(data, himg, SALT_A)

        with open(data, "r+b") as f:
            f.seek(42 * 4096)
            f.write(b"\xff" * 4096)

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is False
        assert rpt["corrupted_blocks"] == [42]

    def test_multiple_corruptions(self, tmp_path):
        """Multiple corrupted blocks are all identified."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        veritysetup_format(data, himg, SALT_A)

        targets = [10, 100, 500]
        with open(data, "r+b") as f:
            for blk in targets:
                f.seek(blk * 4096)
                f.write(b"\xde\xad" * 2048)

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is False
        assert rpt["corrupted_blocks"] == targets

    def test_single_byte_flip(self, tmp_path):
        """Even a single flipped byte is detected."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        veritysetup_format(data, himg, SALT_A)

        with open(data, "r+b") as f:
            f.seek(200 * 4096 + 999)
            orig = f.read(1)
            f.seek(200 * 4096 + 999)
            f.write(bytes([orig[0] ^ 0xFF]))

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0
        rpt = json.loads(r.stdout)
        assert 200 in rpt["corrupted_blocks"]

    def test_combined_image_audit(self, tmp_path):
        """Audit works when data and hash are in the same file."""
        combined = str(tmp_path / "combined.img")
        create_data_image(combined, 4)
        offset = 4 * 1024 * 1024
        ref = veritysetup_format(combined, combined, SALT_B, hash_offset=offset)

        r = run_tool("audit", data=combined, hash=combined, hash_offset=offset)
        assert r.returncode == 0, f"combined audit failed: {r.stderr}"
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is True
        assert rpt["root_hash"] == ref["root_hash"]
        assert rpt["corrupted_blocks"] == []

    def test_audit_sha512(self, tmp_path):
        """Audit works with sha512 algorithm."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A, algorithm="sha512")

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0, f"sha512 audit failed: {r.stderr}"
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is True
        assert rpt["root_hash"] == ref["root_hash"]
        assert rpt["algorithm"] == "sha512"

    def test_audit_1024_data_blocks(self, tmp_path):
        """Audit works with 1024-byte data block size."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A, data_block_size=1024)

        r = run_tool("audit", data=data, hash=himg)
        assert r.returncode == 0, f"1024-block audit failed: {r.stderr}"
        rpt = json.loads(r.stdout)

        assert rpt["tree_valid"] is True
        assert rpt["root_hash"] == ref["root_hash"]
        assert rpt["data_blocks"] == 4 * 1024  # 4MB / 1024


# ---------------------------------------------------------------------------
# DM target table generation tests
# ---------------------------------------------------------------------------
class TestDmTable:

    def test_target_table_fields(self, tmp_path):
        """Target table has correct format and field values."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A)

        r = run_tool(
            "dm-table", data=data, hash=himg,
            data_dev="/dev/sda1", hash_dev="/dev/sda2",
        )
        assert r.returncode == 0, f"dm-table failed: {r.stderr}"
        parts = r.stdout.strip().split()

        assert len(parts) == 13, f"Expected 13 fields, got {len(parts)}: {parts}"
        assert parts[0] == "0"                                   # start sector
        assert int(parts[1]) == ref["data_blocks"] * 4096 // 512  # num sectors
        assert parts[2] == "verity"                               # target type
        assert parts[3] == "1"                                    # version
        assert parts[4] == "/dev/sda1"                            # data dev
        assert parts[5] == "/dev/sda2"                            # hash dev
        assert parts[6] == "4096"                                 # data block size
        assert parts[7] == "4096"                                 # hash block size
        assert int(parts[8]) == ref["data_blocks"]                # num data blocks
        assert parts[9] == "1"                                    # hash_start_block
        assert parts[10] == "sha256"                              # algorithm
        assert parts[11] == ref["root_hash"]                      # root hash
        assert parts[12] == SALT_A                                # salt

    def test_combined_image_hash_start(self, tmp_path):
        """hash_start_block is correct for combined data+hash image."""
        combined = str(tmp_path / "combined.img")
        create_data_image(combined, 4)
        offset = 4 * 1024 * 1024
        veritysetup_format(combined, combined, SALT_A, hash_offset=offset)

        r = run_tool(
            "dm-table", data=combined, hash=combined, hash_offset=offset,
            data_dev="/dev/sda1", hash_dev="/dev/sda1",
        )
        assert r.returncode == 0, f"combined dm-table failed: {r.stderr}"
        parts = r.stdout.strip().split()

        # hash_start_block = (offset + hash_block_size) / hash_block_size
        expected_hs = (offset + 4096) // 4096  # 1025
        assert int(parts[9]) == expected_hs
        assert parts[4] == "/dev/sda1"
        assert parts[5] == "/dev/sda1"

    def test_dm_table_sha512(self, tmp_path):
        """DM table generation works with sha512."""
        data = str(tmp_path / "data.img")
        himg = str(tmp_path / "hash.img")
        create_data_image(data, 4)
        ref = veritysetup_format(data, himg, SALT_A, algorithm="sha512")

        r = run_tool(
            "dm-table", data=data, hash=himg,
            data_dev="/dev/vda2", hash_dev="/dev/vda3",
        )
        assert r.returncode == 0, f"sha512 dm-table failed: {r.stderr}"
        parts = r.stdout.strip().split()

        assert parts[10] == "sha512"
        assert parts[11] == ref["root_hash"]
